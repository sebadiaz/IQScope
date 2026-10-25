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


if __name__ == '__main__':
    unittest.main()
