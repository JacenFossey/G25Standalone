from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
# Do not require hidapi (or a wheel) on the test runner.
with patch.dict(sys.modules, {'hid': Mock()}):
    import g25_service as service


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.output = service.G25Output()
        self.device = Mock()
        self.device.write.return_value = 8
        self.output.device = self.device

    def test_clamps_force(self):
        self.output.set_force(100000, immediate=True)
        self.assertEqual(self.output.current_force_byte, 255)
        self.output.set_force(-100000, immediate=True)
        self.assertEqual(self.output.current_force_byte, 1)

    def test_smooths_before_quantization(self):
        self.output.set_force(10000)
        self.assertEqual(self.output.filtered_force, 3500)
        self.assertEqual(self.output.current_force_byte, service.force_to_wheel_byte(3500))

    def test_safety_neutral_bypasses_smoothing(self):
        self.output.set_force(10000)
        self.output.set_force(0, immediate=True)
        self.assertEqual(self.output.filtered_force, 0)
        self.assertEqual(self.output.current_force_byte, 128)
        self.device.write.assert_called_with(service.make_force_report(0))

    def test_unchanged_quantized_output_is_not_rewritten(self):
        self.output.set_force(0)
        self.device.write.assert_not_called()

    def test_shutdown_neutralizes_then_stops(self):
        self.output.set_force(10000, immediate=True)
        self.device.reset_mock()
        self.output.close()
        self.assertEqual([call.args[0] for call in self.device.write.call_args_list],
                         [service.make_force_report(0), service.STOP_ALL_REPORT])
        self.device.close.assert_called_once()
        self.assertFalse(self.output.connected)

    def test_failed_write_does_not_commit_output_state(self):
        self.device.write.return_value = 0
        with self.assertRaises(OSError):
            self.output.set_force(10000, immediate=True)
        self.assertEqual(self.output.current_force_byte, 128)


class ServiceCleanupTests(unittest.TestCase):
    def test_diagnostic_failure_cannot_skip_neutralization(self):
        output = Mock()
        legacy = Mock()
        server = Mock()

        def broken_cleanup_log(*args, **kwargs):
            if args and str(args[0]).startswith('\n[G25]'):
                raise OSError('log disk failure')

        with patch.object(service, 'create_legacy_ffb_socket', return_value=legacy), \
                patch.object(service, 'FfbServer', return_value=server), \
                patch.object(service, 'G25Output', return_value=output), \
                patch('builtins.print', side_effect=broken_cleanup_log):
            with self.assertRaises(OSError):
                service.main([], stop_requested=lambda: True)
        output.close.assert_called_once_with(send_stop=True)
        server.close.assert_called_once()
        legacy.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
