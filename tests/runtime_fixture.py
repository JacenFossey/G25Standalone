"""Subprocess entry point with fake HID only; never accesses a real wheel."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g25_service
import g25_runtime
from g25_windows import SessionNotifications

args = g25_service.parse_args()
data = args.data_dir


class FakeDevice:
    def open_path(self, _path):
        pass

    def set_nonblocking(self, _value):
        pass

    def write(self, report):
        with (data / "hid-reports.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(list(report)) + "\n")
        return len(report)

    def read(self, _size):
        if (data / "fail-read").exists():
            raise RuntimeError("injected HID read failure")
        return []

    def close(self):
        pass


def enumerate_devices(_vendor, product):
    mode = os.environ.get("G25_TEST_MODE", "native")
    expected = 0xC294 if mode == "compatibility" else 0xC299
    return [{"path": b"test-wheel"}] if mode != "missing" and product == expected else []


class TestSessionNotifications(SessionNotifications):
    def start(self):
        super().start()
        if self.hwnd:
            g25_runtime.write_json(data / "session-window.json", {"hwnd": self.hwnd})


sys.modules["hid"] = types.SimpleNamespace(enumerate=enumerate_devices, device=FakeDevice)
g25_runtime.SessionNotifications = TestSessionNotifications

if __name__ == "__main__":
    raise SystemExit(g25_service.main())
