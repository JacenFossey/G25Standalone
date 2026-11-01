from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SRC = str(Path(__file__).resolve().parents[1] / 'src')
sys.path.insert(0, SRC)
from g25_runtime import object_names, stop_running


class NamesTests(unittest.TestCase):
    def test_names_are_stable_and_isolated_by_user_state_path(self):
        self.assertEqual(object_names(Path('a')), object_names(Path('a')))
        self.assertNotEqual(object_names(Path('a')), object_names(Path('b')))


@unittest.skipUnless(os.name == 'nt', 'Windows named object integration')
class RuntimeTests(unittest.TestCase):
    def helper(self, folder, body):
        code = (f'import sys, time; from pathlib import Path; sys.path.insert(0, {SRC!r}); '
                'from g25_runtime import WindowsRuntime; '
                f'r = WindowsRuntime(Path({folder!r})); ' + body)
        return subprocess.Popen([sys.executable, '-B', '-u', '-c', code],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_duplicate_and_graceful_stop_without_hardware(self):
        with tempfile.TemporaryDirectory() as folder:
            child = self.helper(folder, "assert r.acquire(); print('ready', flush=True)\n"
                                "try:\n while not r.stop_requested(): time.sleep(0.01)\n"
                                "finally: r.close()\n")
            try:
                self.assertEqual(child.stdout.readline().strip(), 'ready')
                duplicate = self.helper(folder, 'print(r.acquire()); r.close()')
                output, errors = duplicate.communicate(timeout=5)
                self.assertEqual(duplicate.returncode, 0, errors)
                self.assertEqual(output.strip(), 'False')
                stop_running(Path(folder), timeout=5)
                _, errors = child.communicate(timeout=5)
                self.assertEqual(child.returncode, 0, errors)
                stop_running(Path(folder), timeout=0.1)  # already stopped is success
            finally:
                if child.poll() is None:
                    child.terminate()  # synthetic helper never owns hardware
                child.communicate(timeout=5)

    def test_stop_timeout_does_not_terminate_process(self):
        with tempfile.TemporaryDirectory() as folder:
            child = self.helper(folder, "assert r.acquire(); print('ready', flush=True); time.sleep(10); r.close()")
            try:
                self.assertEqual(child.stdout.readline().strip(), 'ready')
                with self.assertRaises(TimeoutError):
                    stop_running(Path(folder), timeout=0.05)
                self.assertIsNone(child.poll())
            finally:
                child.terminate()  # synthetic helper never owns hardware
                child.communicate(timeout=5)


@unittest.skipUnless(os.name == 'nt', 'Windows session notification window')
class SessionTests(unittest.TestCase):
    def test_targeted_session_message_requests_stop_and_window_closes(self):
        import threading
        from g25_session import SessionShutdown, WM_QUERYENDSESSION
        stopped = threading.Event()
        session = SessionShutdown(stopped.set)
        try:
            # Post only to our synthetic window, never broadcast or sign out.
            self.assertTrue(session.user32.PostMessageW(session.hwnd, WM_QUERYENDSESSION, 0, 0))
            self.assertTrue(stopped.wait(5))
        finally:
            session.close()
        self.assertFalse(session.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
