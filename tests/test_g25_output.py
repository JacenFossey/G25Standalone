"""Regression coverage for final force smoothing without attached hardware."""

from __future__ import annotations

import pathlib
import sys
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# These tests exercise generated HID reports, so importing the service must not
# require a platform HID library or open a physical wheel.
with mock.patch.dict(sys.modules, {"hid": types.ModuleType("hid")}):
    import g25_service


class G25OutputTests(unittest.TestCase):
    def make_output(self):
        output = g25_service.G25Output()
        device = mock.Mock()
        device.write.side_effect = lambda report: len(report)
        output.device = device
        return output, device

    def test_signed_force_steps_are_smoothed_and_reach_target(self):
        for magnitude in (-10000, 10000):
            with self.subTest(magnitude=magnitude):
                output, device = self.make_output()
                target = g25_service.force_to_wheel_byte(magnitude)
                neutral = g25_service.G25_FORCE_NEUTRAL_BYTE

                output.set_force(magnitude)
                first = device.write.call_args.args[0][3]
                self.assertGreater(first, min(neutral, target))
                self.assertLess(first, max(neutral, target))

                for _ in range(40):
                    output.set_force(magnitude)
                values = [call.args[0][3] for call in device.write.call_args_list]
                self.assertEqual(values[-1], target)
                self.assertEqual(values, sorted(values, reverse=magnitude < 0))

    def test_small_sustained_force_is_not_lost_to_a_deadband(self):
        output, device = self.make_output()
        for _ in range(40):
            output.set_force(100)
        self.assertEqual(
            device.write.call_args.args[0][3],
            g25_service.force_to_wheel_byte(100),
        )
        self.assertGreater(
            device.write.call_args.args[0][3],
            g25_service.G25_FORCE_NEUTRAL_BYTE,
        )

    def test_immediate_neutralization_clears_previous_force(self):
        output, device = self.make_output()
        for _ in range(40):
            output.set_force(10000)

        output.set_force(0, immediate=True)
        self.assertEqual(
            device.write.call_args.args[0],
            g25_service.make_force_report_byte(g25_service.G25_FORCE_NEUTRAL_BYTE),
        )

        # Restarting force after neutralization must behave like a fresh output.
        output.set_force(-10000)
        fresh, fresh_device = self.make_output()
        fresh.set_force(-10000)
        self.assertEqual(
            device.write.call_args.args[0], fresh_device.write.call_args.args[0]
        )


if __name__ == "__main__":
    unittest.main()
