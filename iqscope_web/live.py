"""Receive-only rtl_tcp adapter, with a bounded latest-samples window."""
from collections import deque
import socket
import struct
import threading
import time

import numpy as np
from scipy import signal


def receive_exact(sock, count, stop):
    data = bytearray()
    while len(data) < count:
        if stop.is_set():
            raise InterruptedError('Receiver stopped')
        try:
            block = sock.recv(count-len(data))
        except socket.timeout:
            continue
        if not block:
            raise ConnectionError('rtl_tcp closed the stream')
        data.extend(block)
    return bytes(data)


class LiveReceiver:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.sock = None
        self.blocks = deque()
        self.buffered = 0
        self.total = 0
        self.error = None
        self.connected = False
        self.running = False
        self.started = None
        self.fs = 1_024_000
        self.frequency = 100_000_000
        self.last_data = 0

    def start(self, port, frequency, sample_rate):
        self.stop()
        self.fs, self.frequency = sample_rate, frequency
        self.blocks.clear()
        self.buffered = self.total = 0
        self.error = None
        self.connected = False
        self.stop_event.clear()
        self.started = time.time()
        self.running = True
        self.thread = threading.Thread(target=self._receive, args=(port,), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        sock = self.sock
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self.thread:
            self.thread.join(timeout=4)
            if self.thread.is_alive():
                raise RuntimeError('Previous receiver has not stopped')
        self.running = self.connected = False

    def _receive(self, port):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=3) as sock:
                self.sock = sock
                sock.settimeout(1)
                header = receive_exact(sock, 12, self.stop_event)
                if header[:4] != b'RTL0':
                    raise ValueError('The endpoint is not an rtl_tcp server')
                # Receive only. No SDR transmit commands are implemented.
                for command, value in ((1, self.frequency), (2, self.fs), (3, 0)):
                    sock.sendall(struct.pack('>BI', command, value))
                self.connected = True
                while not self.stop_event.is_set():
                    data = receive_exact(sock, 65536, self.stop_event)
                    values = (np.frombuffer(data, dtype=np.uint8).astype(np.float32)-127.5)/127.5
                    iq = values[::2] + 1j*values[1::2]
                    with self.lock:
                        self.blocks.append(iq)
                        self.buffered += len(iq)
                        self.total += len(iq)
                        while self.blocks and self.buffered-len(self.blocks[0]) >= self.fs:
                            self.buffered -= len(self.blocks.popleft())
                        self.last_data = time.time()
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error = str(exc)
        finally:
            self.sock = None
            self.running = self.connected = False

    def status(self):
        with self.lock:
            total, buffered = self.total, self.buffered
        return {'running': self.running, 'connected': self.connected, 'error': self.error,
                'sample_rate': self.fs, 'center_frequency_hz': self.frequency,
                'received_samples': total, 'buffered_samples': buffered,
                'window_start_sample': total-buffered, 'last_data_time': self.last_data,
                'continuity': 'unknown: rtl_tcp provides no sample timestamps or overflow counters',
                'analysis_mode': 'latest-window snapshots; decoding between snapshots is not guaranteed',
                'tuning': 'requested settings; rtl_tcp provides no tuning readback'}

    def snapshot(self):
        with self.lock:
            if not self.blocks:
                return None, 0
            return np.concatenate(list(self.blocks)), self.total-self.buffered

    def spectrum(self):
        with self.lock:
            if not self.blocks:
                return None
            x = self.blocks[-1].copy()
        f, p = signal.welch(x, self.fs, nperseg=1024, return_onesided=False)
        return {'frequency_hz': np.fft.fftshift(f).tolist(),
                'power_db': (10*np.log10(np.maximum(np.fft.fftshift(p), 1e-30))).tolist(),
                'center_frequency_hz': self.frequency, 'sample_rate': self.fs,
                'received_samples': self.total}
