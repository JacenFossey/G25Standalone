from __future__ import annotations

import math
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ffb_engine import (  # noqa: E402
    DI_MAX,
    EFFECT_CONSTANT,
    EFFECT_CUSTOM,
    EFFECT_DAMPER,
    EFFECT_FRICTION,
    EFFECT_INERTIA,
    EFFECT_RAMP,
    EFFECT_SAW_DOWN,
    EFFECT_SAW_UP,
    EFFECT_SINE,
    EFFECT_SPRING,
    EFFECT_SQUARE,
    EFFECT_TRIANGLE,
    Effect,
    EffectEngine,
    WheelKinematics,
)


class EffectEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = EffectEngine()
        self.engine.connect(1)
        self.kin = WheelKinematics()
        self.base = 100.0

    def put(self, kind: int, **extra):
        message = {
            "op": "effect",
            "id": 1,
            "kind": kind,
            "duration": 1_000_000,
            "gain": DI_MAX,
            "direction": 1,
            "start": False,
            **extra,
        }
        self.engine.handle(1, message)
        self.engine.handle(1, {"op": "start", "id": 1, "iterations": 1, "solo": False})
        effect = self.engine.sessions[1].effects[1]
        effect.started_at = self.base
        return effect

    def render_at(self, seconds: float) -> int:
        return self.engine.render(self.kin, self.base + seconds)

    def test_constant(self):
        self.put(EFFECT_CONSTANT, magnitude=5000)
        self.assertEqual(self.render_at(0.1), 5000)

    def test_ramp(self):
        self.put(EFFECT_RAMP, rampStart=-10000, rampEnd=10000)
        self.assertAlmostEqual(self.render_at(0.5), 0, delta=2)

    def test_square(self):
        self.put(EFFECT_SQUARE, magnitude=5000, period=100_000)
        self.assertEqual(self.render_at(0.01), 5000)
        self.assertEqual(self.render_at(0.06), -5000)

    def test_sine(self):
        self.put(EFFECT_SINE, magnitude=10000, period=1_000_000)
        self.assertAlmostEqual(self.render_at(0.25), 10000, delta=2)

    def test_triangle(self):
        self.put(EFFECT_TRIANGLE, magnitude=10000, period=1_000_000)
        self.assertAlmostEqual(self.render_at(0.5), 10000, delta=2)

    def test_saw_up(self):
        self.put(EFFECT_SAW_UP, magnitude=10000, period=1_000_000)
        self.assertAlmostEqual(self.render_at(0.5), 0, delta=2)

    def test_saw_down(self):
        self.put(EFFECT_SAW_DOWN, magnitude=10000, period=1_000_000)
        self.assertAlmostEqual(self.render_at(0.5), 0, delta=2)

    def test_custom(self):
        self.put(EFFECT_CUSTOM, samplePeriod=100_000, samples=[1000, 2000, -3000])
        self.assertEqual(self.render_at(0.15), 2000)
        self.assertEqual(self.render_at(0.25), -3000)

    def test_spring(self):
        self.kin.position = 0.5
        self.put(
            EFFECT_SPRING,
            condition={
                "offset": 0,
                "positiveCoefficient": -10000,
                "negativeCoefficient": -10000,
                "positiveSaturation": 10000,
                "negativeSaturation": 10000,
                "deadband": 0,
            },
        )
        self.assertLess(self.render_at(0.1), 0)

    def test_damper(self):
        self.kin.velocity = 1.0
        self.put(
            EFFECT_DAMPER,
            condition={
                "positiveCoefficient": -10000,
                "negativeCoefficient": -10000,
                "positiveSaturation": 10000,
                "negativeSaturation": 10000,
            },
        )
        self.assertLess(self.render_at(0.1), 0)

    def test_inertia(self):
        self.kin.acceleration = 2.0
        self.put(
            EFFECT_INERTIA,
            condition={
                "positiveCoefficient": -10000,
                "negativeCoefficient": -10000,
                "positiveSaturation": 10000,
                "negativeSaturation": 10000,
            },
        )
        self.assertLess(self.render_at(0.1), 0)

    def test_friction(self):
        self.kin.velocity = 1.0
        self.put(
            EFFECT_FRICTION,
            condition={
                "positiveCoefficient": -5000,
                "negativeCoefficient": -5000,
                "positiveSaturation": 10000,
                "negativeSaturation": 10000,
            },
        )
        self.assertLess(self.render_at(0.1), 0)

    def test_gain_scales_effect(self):
        self.put(EFFECT_CONSTANT, magnitude=10000, gain=5000)
        self.assertEqual(self.render_at(0.1), 5000)

    def test_device_gain_scales_mixed_output(self):
        self.put(EFFECT_CONSTANT, magnitude=10000)
        self.engine.handle(1, {"op": "gain", "value": 2500})
        self.assertEqual(self.render_at(0.1), 2500)

    def test_reset_restores_actuators(self):
        self.put(EFFECT_CONSTANT, magnitude=5000)
        self.engine.handle(1, {"op": "command", "name": "actuators_off"})
        self.assertEqual(self.render_at(0.1), 0)
        self.engine.handle(1, {"op": "command", "name": "reset"})
        self.assertTrue(self.engine.sessions[1].actuators)


if __name__ == "__main__":
    unittest.main()
