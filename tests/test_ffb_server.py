from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
from ffb_engine import EffectEngine
from ffb_server import Client, FfbServer


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.engine = EffectEngine()
        self.engine.connect(1)
        self.sock = Mock()
        self.server = FfbServer.__new__(FfbServer)
        self.server.engine = self.engine
        self.server.selector = Mock()
        self.server.clients = {1: Client(self.sock)}

    def feed(self, data):
        self.sock.recv.return_value = data
        self.server._read(1)

    def test_invalid_shapes_do_not_crash(self):
        for data in (b'null\n', b'[]\n', b'1\n', b'"bad"\n',
                     b'{"op":"effect","id":1,"kind":0,"envelope":1}\n'):
            self.feed(data)
        self.feed(b'{"op":"gain","value":5000}\n')
        self.assertEqual(self.engine.sessions[1].device_gain, 5000)

    def test_split_and_batched_messages(self):
        self.feed(b'{"op":"ga')
        self.feed(b'in","value":5000}\n{"op":"gain","value":2500}\n')
        self.assertEqual(self.engine.sessions[1].device_gain, 2500)

    def test_disconnect_removes_force_state(self):
        self.feed(b'{"op":"effect","id":1,"kind":0,"magnitude":5000,"start":true}\n')
        self.assertTrue(self.engine.has_active_effects())
        self.feed(b'')
        self.assertFalse(self.engine.sessions)
        self.sock.close.assert_called_once()

    def test_large_complete_line_rejected(self):
        import ffb_server
        with unittest.mock.patch.object(ffb_server, 'MAX_LINE', 16):
            self.feed(b' ' * 17 + b'\n')
        self.assertNotIn(1, self.server.clients)

    def test_large_trailing_partial_line_rejected(self):
        import ffb_server
        with unittest.mock.patch.object(ffb_server, 'MAX_LINE', 16):
            self.feed(b'{}\n' + b' ' * 17)
        self.assertNotIn(1, self.server.clients)


if __name__ == '__main__':
    unittest.main()
