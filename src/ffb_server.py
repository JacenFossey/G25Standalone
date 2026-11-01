"""Local IPC endpoint for the registered DirectInput FFB driver.

Wire format: newline-delimited JSON over TCP on 127.0.0.1:26726.  The protocol is
intentionally local-only and small; the game-side DLL owns DirectInput object
semantics, while the service owns effect rendering and all hardware I/O.
"""

from __future__ import annotations

import json
import logging
import selectors
import socket
from dataclasses import dataclass, field
from typing import Any

from ffb_engine import EffectEngine

HOST = "127.0.0.1"
PORT = 26726
MAX_LINE = 1_000_000
LOG = logging.getLogger('g25.ipc')


@dataclass
class Client:
    sock: socket.socket
    buffer: bytearray = field(default_factory=bytearray)


class FfbServer:
    def __init__(self, engine: EffectEngine) -> None:
        self.engine = engine
        self.selector = selectors.DefaultSelector()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((HOST, PORT))
        self.listener.listen()
        self.listener.setblocking(False)
        self.selector.register(self.listener, selectors.EVENT_READ, None)
        self.clients: dict[int, Client] = {}
        self._next_client_id = 1

    def close(self) -> None:
        for client_id in list(self.clients):
            self._drop(client_id)
        try:
            self.selector.unregister(self.listener)
        except Exception:
            pass
        try:
            self.listener.close()
        except Exception:
            pass
        self.selector.close()

    def poll(self) -> None:
        for key, _mask in self.selector.select(timeout=0):
            if key.data is None:
                self._accept()
            else:
                self._read(int(key.data))

    def _accept(self) -> None:
        while True:
            try:
                sock, _address = self.listener.accept()
            except BlockingIOError:
                return
            sock.setblocking(False)
            client_id = self._next_client_id
            self._next_client_id += 1
            self.clients[client_id] = Client(sock)
            self.engine.connect(client_id)
            LOG.info('DirectInput client %s connected.', client_id)
            self.selector.register(sock, selectors.EVENT_READ, client_id)

    def _read(self, client_id: int) -> None:
        client = self.clients.get(client_id)
        if client is None:
            return
        try:
            data = client.sock.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            self._drop(client_id)
            return

        if not data:
            self._drop(client_id)
            return

        client.buffer.extend(data)
        while True:
            newline = client.buffer.find(b"\n")
            if newline > MAX_LINE or (newline < 0 and len(client.buffer) > MAX_LINE):
                LOG.warning('Dropping oversized IPC frame from client %s.', client_id)
                self._drop(client_id)
                return
            if newline < 0:
                break
            raw = bytes(client.buffer[:newline])
            del client.buffer[: newline + 1]
            if not raw:
                continue
            try:
                message: dict[str, Any] = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(message, dict):
                continue
            try:
                self.engine.handle(client_id, message)
            except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
                # A malformed game-side packet must never take down wheel output.
                continue

    def _drop(self, client_id: int) -> None:
        client = self.clients.pop(client_id, None)
        self.engine.disconnect(client_id)
        if client is None:
            return
        LOG.info('DirectInput client %s disconnected; effects removed.', client_id)
        try:
            self.selector.unregister(client.sock)
        except Exception:
            pass
        try:
            client.sock.close()
        except Exception:
            pass
