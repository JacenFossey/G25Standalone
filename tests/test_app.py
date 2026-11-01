from __future__ import annotations

import json
import logging
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
import g25_app


class SettingsTests(unittest.TestCase):
    def test_defaults_created_and_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'settings.json'
            self.assertEqual(g25_app.load_settings(path), 900)
            path.write_text(json.dumps({'range_degrees': 540}), encoding='utf-8')
            self.assertEqual(g25_app.load_settings(path), 540)

    def test_invalid_settings_not_overwritten(self):
        for value in (39, 901, True, '540', None):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as folder:
                path = pathlib.Path(folder) / 'settings.json'
                original = json.dumps({'range_degrees': value})
                path.write_text(original, encoding='utf-8')
                with self.assertRaises(ValueError):
                    g25_app.load_settings(path)
                self.assertEqual(path.read_text(encoding='utf-8'), original)

    def test_invalid_document(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'settings.json'
            path.write_text('[]', encoding='utf-8')
            with self.assertRaises(ValueError):
                g25_app.load_settings(path)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.logging_patch = patch.object(g25_app, 'configure_logging')
        self.logging_patch.start()
        self.addCleanup(self.logging_patch.stop)
        self.session_patch = patch.object(g25_app, 'SessionShutdown')
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)

    def test_duplicate_does_not_start_hardware(self):
        runtime = Mock()
        runtime.acquire.return_value = False
        with patch.object(g25_app, 'WindowsRuntime', return_value=runtime), \
                patch.object(g25_app, 'run_service') as service:
            self.assertEqual(g25_app.start_background(pathlib.Path('unused')), 0)
        service.assert_not_called()
        runtime.close.assert_called_once()

    def test_runtime_closed_on_service_failure(self):
        runtime = Mock()
        runtime.acquire.return_value = True
        with patch.object(g25_app, 'WindowsRuntime', return_value=runtime), \
                patch.object(g25_app, 'load_settings', return_value=540), \
                patch.object(g25_app, 'run_service', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                g25_app.start_background(pathlib.Path('unused'))
        runtime.close.assert_called_once()

    def test_persisted_range_and_stop_callback_forwarded(self):
        runtime = Mock()
        runtime.acquire.return_value = True
        with patch.object(g25_app, 'WindowsRuntime', return_value=runtime), \
                patch.object(g25_app, 'load_settings', return_value=540), \
                patch.object(g25_app, 'run_service', return_value=0) as service:
            self.assertEqual(g25_app.start_background(pathlib.Path('unused')), 0)
        service.assert_called_once_with(['--range', '540'], stop_requested=runtime.stop_requested)

    def test_registration_uses_bundled_files_and_hidden_powershell(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            (root / 'scripts').mkdir()
            (root / 'scripts' / 'Register-G25StandaloneFF.ps1').touch()
            for bits in ('x86', 'x64'):
                (root / 'drivers' / bits).mkdir(parents=True)
                (root / 'drivers' / bits / 'g25ff.dll').touch()
            with patch.object(g25_app.subprocess, 'run') as run:
                run.return_value = Mock(returncode=0, stdout='registered')
                g25_app.register_driver(root, 'Install')
            args = run.call_args.args[0]
            self.assertIn('-Dll32', args)
            self.assertIn(str(root / 'drivers' / 'x64' / 'g25ff.dll'), args)
            self.assertFalse(run.call_args.kwargs.get('shell', False))


class LoggingTests(unittest.TestCase):
    def test_rotation_failure_never_relogs_to_redirected_stderr(self):
        with tempfile.TemporaryDirectory() as folder:
            handler = g25_app.SafeRotatingFileHandler(pathlib.Path(folder) / 'service.log',
                                                      maxBytes=10, backupCount=1)
            try:
                with patch.object(handler, 'shouldRollover', return_value=True), \
                        patch.object(handler, 'doRollover', side_effect=PermissionError('file in use')), \
                        patch.object(g25_app.LOG, 'log') as relog, \
                        patch('sys.stderr', g25_app.LogStream(logging.ERROR)):
                    handler.emit(logging.LogRecord('test', logging.INFO, '', 0, 'test', (), None))
                    relog.assert_not_called()
            finally:
                handler.close()


if __name__ == '__main__':
    unittest.main()
