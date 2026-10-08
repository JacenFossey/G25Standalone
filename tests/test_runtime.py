from __future__ import annotations

import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g25_runtime as runtime
from g25_windows import SessionNotifications, WM_ENDSESSION, WM_QUERYENDSESSION

FIXTURE = ROOT / "tests/runtime_fixture.py"


class SettingsAndLoggingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)

    def tearDown(self):
        runtime.close_logging()
        self.directory.cleanup()

    def test_saved_range_survives_reload_and_invalid_update(self):
        self.assertEqual(runtime.load_settings(self.root)["steering_range"], 900)
        runtime.save_range(self.root, 540)
        saved = (self.root / "settings.json").read_bytes()
        for value in (39, 901, True, "540"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runtime.save_range(self.root, value)
        self.assertEqual((self.root / "settings.json").read_bytes(), saved)
        self.assertEqual(runtime.load_settings(self.root)["steering_range"], 540)

    def test_corrupt_or_newer_settings_are_not_silently_overwritten(self):
        for value in ("bad json", '{"version": 2}', '{"version": 1, "steering_range": false}'):
            (self.root / "settings.json").write_text(value)
            with self.assertRaises(ValueError):
                runtime.save_range(self.root, 540)
            self.assertEqual((self.root / "settings.json").read_text(), value)

    def test_settings_update_preserves_other_fields(self):
        runtime.write_json(self.root / "settings.json", {
            "version": 1, "steering_range": 900, "future_option": True,
        })
        self.assertTrue(runtime.save_range(self.root, 540)["future_option"])
        self.assertFalse(list(self.root.glob("settings.json.*")))

    def test_background_logging_rotates_without_console_streams(self):
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
            runtime.configure_logging(self.root, background=True)
            handler = runtime.LOG.handlers[0]
            handler.maxBytes = 256
            for index in range(100):
                runtime.LOG.info("Lifecycle event %s %s", index, "x" * 50)
        runtime.close_logging()
        files = list((self.root / "logs").glob("g25.log*"))
        self.assertEqual(len(files), 4)
        self.assertTrue(all(file.stat().st_size <= 256 for file in files))
        self.assertIn("Lifecycle event 99", (self.root / "logs/g25.log").read_text())

    def test_management_commands_do_not_require_hid(self):
        for action, expected in (("settings", 0), ("status", 3), ("stop", 0)):
            with self.subTest(action=action):
                # -S disables site packages, including any installed hidapi.
                result = subprocess.run([
                    sys.executable, "-S", str(ROOT / "src/g25_service.py"), action,
                    "--data-dir", str(self.root),
                ], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, expected, result.stderr)


class SessionMessageTests(unittest.TestCase):
    def test_cancelled_shutdown_does_not_stop_the_app(self):
        stop = mock.Mock()
        finished = threading.Event()
        finished.set()
        notifications = SessionNotifications(stop, finished)
        self.assertEqual(notifications.session_message(WM_QUERYENDSESSION, True), 1)
        self.assertEqual(notifications.session_message(WM_ENDSESSION, False), 0)
        stop.assert_not_called()
        self.assertEqual(notifications.session_message(WM_ENDSESSION, True), 0)
        stop.assert_called_once_with("Windows session ending")


class RuntimeProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        self.process = None

    def tearDown(self):
        try:
            runtime.stop_process(self.root, timeout=5)
        except (OSError, RuntimeError):
            if self.process is not None and self.process.poll() is None:
                self.process.kill()  # Test-process cleanup only; never production stop.
        if self.process is not None:
            self.process.communicate(timeout=10)
        self.directory.cleanup()

    def command(self, action, *arguments):
        return subprocess.run([
            sys.executable, str(FIXTURE), action, "--data-dir", str(self.root), *arguments,
        ], capture_output=True, text=True, timeout=15)

    def wait_for(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            if self.process is not None and self.process.poll() is not None:
                _stdout, stderr = self.process.communicate()
                self.fail(f"Runtime exited early: {stderr}")
            time.sleep(0.02)
        self.fail("Timed out waiting for runtime")

    def start(self, mode="native", *arguments):
        self.process = subprocess.Popen([
            sys.executable, str(FIXTURE), "run", "--background",
            "--data-dir", str(self.root), *arguments,
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, "G25_TEST_MODE": mode})
        expected = "ready" if mode == "native" else "initializing" if mode == "compatibility" else "waiting"
        self.wait_for(lambda: (runtime.query_status(self.root) or {}).get("state") == expected)
        return runtime.query_status(self.root)

    def reports(self):
        return [json.loads(line) for line in (self.root / "hid-reports.jsonl").read_text().splitlines()]

    def assert_neutralized(self):
        self.assertEqual(self.reports()[-2:], [
            [0, 0x11, 0x08, 0x80, 0x80, 0, 0, 0],
            [0, 0xF3, 0, 0, 0, 0, 0, 0],
        ])

    def test_duplicate_run_cannot_replace_live_instance_or_settings(self):
        runtime.save_range(self.root, 540)
        status = self.start()
        endpoint = runtime.read_endpoint(self.root)
        result = self.command("run", "--range", "360")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(runtime.read_endpoint(self.root), endpoint)
        self.assertEqual(runtime.query_status(self.root)["pid"], status["pid"])
        self.assertEqual(runtime.query_status(self.root)["steering_range"], 540)
        self.assertEqual(runtime.load_settings(self.root)["steering_range"], 540)

    def test_stop_waits_for_neutralization_after_active_force(self):
        self.start()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto((5000).to_bytes(4, "big", signed=True), ("127.0.0.1", 26725))
        self.wait_for(lambda: any(report[1:3] == [0x11, 0x08] and report[3] != 0x80
                                 for report in self.reports()))
        result = self.command("stop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_neutralized()
        self.assertFalse((self.root / "runtime.json").exists())
        self.assertEqual(self.process.wait(timeout=5), 0)

    def test_background_start_is_idempotent_and_range_override_is_temporary(self):
        runtime.save_range(self.root, 540)
        result = self.command("start", "--range", "360")
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(result.stdout)
        self.assertEqual(status["steering_range"], 360)
        again = self.command("start")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads(again.stdout)["pid"], status["pid"])
        self.assertEqual(runtime.load_settings(self.root)["steering_range"], 540)
        self.assertEqual(self.command("stop").returncode, 0)
        restarted = self.command("start")
        self.assertEqual(restarted.returncode, 0, restarted.stderr)
        self.assertEqual(json.loads(restarted.stdout)["steering_range"], 540)

    def test_saved_setting_applies_only_after_restart(self):
        self.start()
        self.assertEqual(self.command("settings", "--range", "540").returncode, 0)
        self.assertEqual(runtime.query_status(self.root)["steering_range"], 900)
        runtime.stop_process(self.root)
        self.process.communicate(timeout=5)
        self.start()
        self.assertEqual(runtime.query_status(self.root)["steering_range"], 540)

    def test_stale_endpoint_after_crash_does_not_prevent_restart(self):
        self.start()
        self.process.kill()
        self.process.communicate(timeout=5)
        self.assertIsNone(runtime.query_status(self.root))
        runtime.stop_process(self.root)  # No PID termination based on stale data.
        self.start()
        self.assertEqual(runtime.query_status(self.root)["state"], "ready")

    def test_unauthenticated_control_cannot_stop_runtime(self):
        self.start()
        endpoint = runtime.read_endpoint(self.root)
        endpoint["token"] = "0" * 64
        with self.assertRaises(OSError):
            runtime.control_request(endpoint, "stop")
        self.assertEqual(runtime.query_status(self.root)["state"], "ready")

    def test_failed_hid_loop_still_neutralizes_and_releases_runtime(self):
        self.start()
        (self.root / "fail-read").touch()
        self.assertEqual(self.process.wait(timeout=5), 1)
        self.assert_neutralized()
        self.assertIsNone(runtime.query_status(self.root))
        self.assertIn("injected HID read failure", (self.root / "logs/g25.log").read_text())

    def test_stop_during_native_mode_switch_is_prompt(self):
        self.start("compatibility")
        started = time.monotonic()
        runtime.stop_process(self.root)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(self.process.wait(timeout=5), 0)

    def test_runtime_without_wheel_reports_waiting_and_can_stop(self):
        status = self.start("missing")
        self.assertEqual(status["wheel"], "disconnected")
        self.assertEqual(self.command("stop").returncode, 0)

    @unittest.skipIf(os.name == "nt", "Windows uses session notifications without a console")
    def test_sigterm_runs_cooperative_cleanup(self):
        self.start()
        self.process.send_signal(signal.SIGTERM)
        self.assertEqual(self.process.wait(timeout=5), 0)
        self.assert_neutralized()

    @unittest.skipUnless(os.name == "nt", "Windows session notification integration")
    def test_windows_session_end_runs_hardware_cleanup(self):
        import ctypes
        from ctypes import wintypes

        self.start()
        hwnd = json.loads((self.root / "session-window.json").read_text())["hwnd"]
        send = ctypes.WinDLL("user32", use_last_error=True).SendMessageTimeoutW
        send.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t,
                         wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        send.restype = ctypes.c_ssize_t
        result = ctypes.c_size_t()
        self.assertTrue(send(hwnd, WM_ENDSESSION, 1, 0, 2, 5000, ctypes.byref(result)))
        self.assertEqual(self.process.wait(timeout=5), 0)
        self.assert_neutralized()


class ControlFailureTests(unittest.TestCase):
    def test_unresponsive_owner_is_not_force_killed_or_reported_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            lock = runtime.InstanceLock(root)
            lock.acquire()
            try:
                with self.assertRaises(RuntimeError):
                    runtime.stop_process(root, timeout=0.1)
            finally:
                lock.release()

    def test_missing_stop_ack_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            with runtime.Runtime(root, 900, background=True) as owner:
                owner.update(state="waiting")
                with self.assertRaises(TimeoutError):
                    runtime.stop_process(root, timeout=0.1)
                self.assertTrue(owner.stop_event.is_set())

    def test_control_failure_cleanup_does_not_leave_an_instance_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            with mock.patch.object(runtime, "SessionNotifications") as notifications:
                notifications.return_value.start.side_effect = RuntimeError("injected failure")
                with self.assertRaises(RuntimeError):
                    with runtime.Runtime(root, 900, background=True):
                        pass
            lock = runtime.InstanceLock(root)
            lock.acquire()
            lock.release()
            self.assertFalse((root / "runtime.json").exists())


if __name__ == "__main__":
    unittest.main()
