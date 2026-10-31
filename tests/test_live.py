"""rtl_tcp wire contract tested in memory, without requiring a radio or socket."""
import socket
import struct
import threading
import unittest
from unittest.mock import patch

import numpy as np

from iqscope_web.live import LiveReceiver, receive_exact


class FakeSocket:
    def __init__(self, content):
        self.content = bytearray(content)
        self.commands = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def settimeout(self, value):
        pass

    def recv(self, count):
        # Fragment reads to check assembly independently of network packet sizes.
        count = min(count, 701, len(self.content))
        data = bytes(self.content[:count])
        del self.content[:count]
        return data

    def sendall(self, content):
        self.commands.extend(content)


class LiveTests(unittest.TestCase):
    def test_wire_commands_conversion_and_bounded_window(self):
        block = bytes([255, 0]) * 32768
        endpoint = FakeSocket(b'RTL0'+struct.pack('>II', 5, 29)+block*12)
        receiver = LiveReceiver()
        receiver.fs = 256000
        receiver.frequency = 1090000000
        with patch('iqscope_web.live.socket.create_connection', return_value=endpoint):
            receiver._receive(1234)
        self.assertEqual(bytes(endpoint.commands), b''.join(struct.pack('>BI', *v) for v in ((1,1090000000),(2,256000),(3,0))))
        data, start = receiver.snapshot()
        self.assertTrue(np.allclose(data, 1-1j))
        self.assertLessEqual(len(data), 256000+32768)
        self.assertEqual(start+len(data), 12*32768)
        self.assertFalse(receiver.status()['connected'])
        self.assertIn('closed', receiver.status()['error'])
        self.assertEqual(len(receiver.spectrum()['power_db']), 1024)

    def test_invalid_header_is_rejected(self):
        receiver = LiveReceiver()
        with patch('iqscope_web.live.socket.create_connection', return_value=FakeSocket(b'NOTRTL123456')):
            receiver._receive(1234)
        self.assertIn('not an rtl_tcp', receiver.error)
        self.assertEqual(receiver.total, 0)

    def test_stopped_receiver_does_not_wait_for_bytes(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(InterruptedError):
            receive_exact(FakeSocket(b''), 12, stop)

    def test_snapshot_context_keeps_samples_and_metadata_together(self):
        receiver=LiveReceiver();receiver.fs=256000;receiver.frequency=868000000
        source=np.ones(2048,dtype=complex);receiver.blocks.append(source)
        receiver.buffered=len(source);receiver.total=10000;receiver.connected=True
        context=receiver.snapshot_context()
        session=context['session_id']
        receiver.fs=1024000;receiver.frequency=100000000;source[:]=0
        self.assertEqual(context['sample_rate'],256000)
        self.assertEqual(context['center_frequency_hz'],868000000)
        self.assertEqual(context['source_sample_start'],10000-2048)
        self.assertTrue(np.all(context['samples']==1))
        self.assertEqual(receiver.status()['session_id'],session)
        self.assertEqual(receiver.spectrum()['session_id'],session)

    def test_restart_changes_session_and_clears_old_window(self):
        receiver=LiveReceiver();previous=receiver.status()['session_id']
        receiver.blocks.append(np.ones(1024,complex));receiver.buffered=receiver.total=1024
        with patch('iqscope_web.live.threading.Thread') as thread:
            thread.return_value.is_alive.return_value=False
            receiver.start(1234,100000000,256000)
            first=receiver.status()['session_id']
            receiver.start(1234,868000000,1024000)
            second=receiver.status()['session_id']
        self.assertNotEqual(previous,first)
        self.assertNotEqual(first,second)
        context=receiver.snapshot_context()
        self.assertIsNone(context['samples'])
        self.assertEqual(context['sample_rate'],1024000)
        self.assertEqual(context['center_frequency_hz'],868000000)
        self.assertEqual(receiver.status()['received_samples'],0)


if __name__ == '__main__':
    unittest.main()
