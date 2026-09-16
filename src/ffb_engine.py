"""DirectInput force-feedback state/rendering for G25Standalone.

The registered DirectInput driver sends effect definitions and lifecycle events
here over localhost TCP.  The service remains the only process that touches the
wheel hardware.

The engine implements the 12 standard DirectInput effect types:
constant, ramp, square, sine, triangle, sawtooth up/down, spring, damper,
inertia, friction, and custom force.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

DI_MAX = 10_000
INFINITE = 0xFFFFFFFF

EFFECT_CONSTANT = 0
EFFECT_RAMP = 1
EFFECT_SQUARE = 2
EFFECT_SINE = 3
EFFECT_TRIANGLE = 4
EFFECT_SAW_UP = 5
EFFECT_SAW_DOWN = 6
EFFECT_SPRING = 7
EFFECT_DAMPER = 8
EFFECT_INERTIA = 9
EFFECT_FRICTION = 10
EFFECT_CUSTOM = 11

CONDITION_EFFECTS = {
    EFFECT_SPRING,
    EFFECT_DAMPER,
    EFFECT_INERTIA,
    EFFECT_FRICTION,
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class WheelKinematics:
    """Normalized wheel position and simple derivatives for condition effects."""

    position: float = 0.0      # -1 .. +1
    velocity: float = 0.0      # normalized travel / second
    acceleration: float = 0.0  # normalized travel / second^2
    _last_position: float | None = None
    _last_velocity: float = 0.0
    _last_time: float | None = None

    def update_raw(self, steering: int, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        position = clamp((steering - 8191.5) / 8191.5, -1.0, 1.0)

        if self._last_position is None or self._last_time is None:
            self.position = position
            self._last_position = position
            self._last_time = now
            return

        dt = now - self._last_time
        if dt <= 0.0001:
            self.position = position
            return

        # HID reports are frequent enough that the raw derivative is useful, but
        # a little smoothing prevents 1-count encoder noise becoming damper buzz.
        raw_velocity = (position - self._last_position) / dt
        velocity = self._last_velocity * 0.65 + raw_velocity * 0.35
        raw_accel = (velocity - self._last_velocity) / dt
        acceleration = self.acceleration * 0.75 + raw_accel * 0.25

        self.position = position
        self.velocity = velocity
        self.acceleration = acceleration
        self._last_position = position
        self._last_velocity = velocity
        self._last_time = now

    def settle_if_stale(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self._last_time is None:
            return
        if now - self._last_time > 0.050:
            self.velocity *= 0.6
            self.acceleration *= 0.4
            if abs(self.velocity) < 0.001:
                self.velocity = 0.0
            if abs(self.acceleration) < 0.01:
                self.acceleration = 0.0


@dataclass
class Effect:
    effect_id: int
    kind: int
    duration: int = INFINITE
    gain: int = DI_MAX
    start_delay: int = 0
    direction: int = 1

    attack_level: int = 0
    attack_time: int = 0
    fade_level: int = 0
    fade_time: int = 0
    has_envelope: bool = False

    magnitude: int = 0
    ramp_start: int = 0
    ramp_end: int = 0
    offset: int = 0
    phase: int = 0
    period: int = 10_000

    condition_offset: int = 0
    positive_coefficient: int = 0
    negative_coefficient: int = 0
    positive_saturation: int = DI_MAX
    negative_saturation: int = DI_MAX
    deadband: int = 0

    custom_sample_period: int = 1_000
    custom_samples: list[int] = field(default_factory=list)

    playing: bool = False
    iterations: int = 1
    started_at: float = 0.0

    @classmethod
    def from_message(cls, message: dict[str, Any]) -> "Effect":
        envelope = message.get("envelope") or {}
        condition = message.get("condition") or {}
        return cls(
            effect_id=int(message["id"]),
            kind=int(message["kind"]),
            duration=int(message.get("duration", INFINITE)),
            gain=int(clamp(int(message.get("gain", DI_MAX)), 0, DI_MAX)),
            start_delay=max(0, int(message.get("delay", 0))),
            direction=-1 if int(message.get("direction", 1)) < 0 else 1,
            attack_level=int(clamp(int(envelope.get("attackLevel", 0)), 0, DI_MAX)),
            attack_time=max(0, int(envelope.get("attackTime", 0))),
            fade_level=int(clamp(int(envelope.get("fadeLevel", 0)), 0, DI_MAX)),
            fade_time=max(0, int(envelope.get("fadeTime", 0))),
            has_envelope=bool(envelope),
            magnitude=int(clamp(int(message.get("magnitude", 0)), -DI_MAX, DI_MAX)),
            ramp_start=int(clamp(int(message.get("rampStart", 0)), -DI_MAX, DI_MAX)),
            ramp_end=int(clamp(int(message.get("rampEnd", 0)), -DI_MAX, DI_MAX)),
            offset=int(clamp(int(message.get("offset", 0)), -DI_MAX, DI_MAX)),
            phase=int(message.get("phase", 0)) % 36_000,
            period=max(1, int(message.get("period", 10_000))),
            condition_offset=int(clamp(int(condition.get("offset", 0)), -DI_MAX, DI_MAX)),
            positive_coefficient=int(clamp(int(condition.get("positiveCoefficient", 0)), -DI_MAX, DI_MAX)),
            negative_coefficient=int(clamp(int(condition.get("negativeCoefficient", 0)), -DI_MAX, DI_MAX)),
            positive_saturation=int(clamp(int(condition.get("positiveSaturation", DI_MAX)), 0, DI_MAX)),
            negative_saturation=int(clamp(int(condition.get("negativeSaturation", DI_MAX)), 0, DI_MAX)),
            deadband=int(clamp(int(condition.get("deadband", 0)), 0, DI_MAX * 2)),
            custom_sample_period=max(1, int(message.get("samplePeriod", 1_000))),
            custom_samples=[
                int(clamp(int(value), -DI_MAX, DI_MAX))
                for value in message.get("samples", [])
            ],
        )


@dataclass
class Session:
    device_id: int = 0
    device_gain: int = DI_MAX
    actuators: bool = True
    paused: bool = False
    stopped: bool = True
    pause_started: float = 0.0
    effects: dict[int, Effect] = field(default_factory=dict)


class EffectEngine:
    def __init__(self) -> None:
        self.sessions: dict[int, Session] = {}

    def connect(self, client_id: int) -> None:
        self.sessions[client_id] = Session()

    def disconnect(self, client_id: int) -> None:
        self.sessions.pop(client_id, None)

    def handle(self, client_id: int, message: dict[str, Any]) -> None:
        session = self.sessions.setdefault(client_id, Session())
        op = message.get("op")

        if op == "device":
            if bool(message.get("begin", True)):
                session.device_id = int(message.get("device", 0))
                session.effects.clear()
                session.device_gain = DI_MAX
                session.actuators = True
                session.paused = False
                session.stopped = True
            else:
                self.disconnect(client_id)
            return

        if op == "gain":
            session.device_gain = int(clamp(int(message.get("value", DI_MAX)), 0, DI_MAX))
            return

        if op == "effect":
            effect = Effect.from_message(message)
            old = session.effects.get(effect.effect_id)
            if old is not None:
                effect.playing = old.playing
                effect.iterations = old.iterations
                effect.started_at = old.started_at
            session.effects[effect.effect_id] = effect
            if bool(message.get("start", False)):
                self._start(session, effect.effect_id, int(message.get("iterations", 1)), False)
            return

        if op == "destroy":
            session.effects.pop(int(message.get("id", 0)), None)
            return

        if op == "start":
            self._start(
                session,
                int(message.get("id", 0)),
                int(message.get("iterations", 1)),
                bool(message.get("solo", False)),
            )
            return

        if op == "stop":
            effect = session.effects.get(int(message.get("id", 0)))
            if effect is not None:
                effect.playing = False
            return

        if op == "command":
            self._command(session, str(message.get("name", "")))

    def _start(self, session: Session, effect_id: int, iterations: int, solo: bool) -> None:
        effect = session.effects.get(effect_id)
        if effect is None:
            return
        if solo:
            for other in session.effects.values():
                other.playing = False
        effect.playing = True
        effect.iterations = iterations if iterations else 1
        effect.started_at = time.monotonic()
        session.stopped = False

    def _command(self, session: Session, name: str) -> None:
        now = time.monotonic()
        if name == "reset":
            session.effects.clear()
            session.stopped = True
            session.paused = False
            session.actuators = True
        elif name == "stopall":
            for effect in session.effects.values():
                effect.playing = False
            session.stopped = True
            session.paused = False
        elif name == "pause":
            if not session.paused:
                session.paused = True
                session.pause_started = now
        elif name == "continue":
            if session.paused:
                delta = now - session.pause_started
                for effect in session.effects.values():
                    if effect.playing:
                        effect.started_at += delta
                session.paused = False
        elif name == "actuators_on":
            session.actuators = True
        elif name == "actuators_off":
            session.actuators = False

    def has_active_effects(self) -> bool:
        for session in self.sessions.values():
            if not session.actuators or session.paused or session.stopped:
                continue
            if any(effect.playing for effect in session.effects.values()):
                return True
        return False

    def render(self, kinematics: WheelKinematics, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        kinematics.settle_if_stale(now)
        total = 0.0

        for session in self.sessions.values():
            if not session.actuators or session.paused or session.stopped:
                continue
            for effect in session.effects.values():
                if not effect.playing:
                    continue
                level = self._render_effect(effect, kinematics, now)
                level *= session.device_gain / DI_MAX
                total += level

        return int(round(clamp(total, -DI_MAX, DI_MAX)))

    def _timing(self, effect: Effect, now: float) -> tuple[int, int] | None:
        elapsed = int((now - effect.started_at) * 1_000_000) - effect.start_delay
        if elapsed < 0:
            return None
        if effect.duration == 0:
            effect.playing = False
            return None
        if effect.duration == INFINITE:
            return elapsed, elapsed

        cycle = elapsed // effect.duration
        if effect.iterations != INFINITE and cycle >= effect.iterations:
            effect.playing = False
            return None
        return elapsed, elapsed % effect.duration

    def _render_effect(
        self,
        effect: Effect,
        kinematics: WheelKinematics,
        now: float,
    ) -> float:
        timing = self._timing(effect, now)
        if timing is None:
            return 0.0
        _elapsed, in_cycle = timing

        if effect.kind == EFFECT_CONSTANT:
            level = self._envelope(effect, effect.magnitude, in_cycle)
        elif effect.kind == EFFECT_RAMP:
            if effect.duration in (0, INFINITE):
                level = effect.ramp_start
            else:
                fraction = clamp(in_cycle / effect.duration, 0.0, 1.0)
                level = effect.ramp_start + (effect.ramp_end - effect.ramp_start) * fraction
            level = self._envelope(effect, level, in_cycle)
        elif effect.kind in {
            EFFECT_SQUARE,
            EFFECT_SINE,
            EFFECT_TRIANGLE,
            EFFECT_SAW_UP,
            EFFECT_SAW_DOWN,
        }:
            wave = self._wave(effect, in_cycle)
            magnitude = self._envelope(effect, effect.magnitude, in_cycle)
            level = effect.offset + wave * magnitude
        elif effect.kind == EFFECT_CUSTOM:
            if not effect.custom_samples:
                level = 0.0
            else:
                index = (in_cycle // effect.custom_sample_period) % len(effect.custom_samples)
                level = self._envelope(effect, effect.custom_samples[index], in_cycle)
        elif effect.kind in CONDITION_EFFECTS:
            level = self._condition(effect, kinematics)
        else:
            level = 0.0

        level *= effect.gain / DI_MAX
        level *= effect.direction
        return clamp(level, -DI_MAX, DI_MAX)

    def _envelope(self, effect: Effect, level: float, in_cycle: int) -> float:
        if not effect.has_envelope or level == 0:
            return level

        sign = -1.0 if level < 0 else 1.0
        magnitude = abs(level)

        if effect.attack_time and in_cycle < effect.attack_time:
            fraction = in_cycle / effect.attack_time
            magnitude = effect.attack_level + (magnitude - effect.attack_level) * fraction

        if (
            effect.duration != INFINITE
            and effect.fade_time
            and in_cycle + effect.fade_time > effect.duration
        ):
            fade_elapsed = in_cycle + effect.fade_time - effect.duration
            fraction = clamp(fade_elapsed / effect.fade_time, 0.0, 1.0)
            magnitude = magnitude + (effect.fade_level - magnitude) * fraction

        return sign * magnitude

    def _wave(self, effect: Effect, in_cycle: int) -> float:
        cycles = in_cycle / effect.period + effect.phase / 36_000.0
        phase = cycles - math.floor(cycles)

        if effect.kind == EFFECT_SINE:
            return math.sin(phase * math.tau)
        if effect.kind == EFFECT_SQUARE:
            return 1.0 if phase < 0.5 else -1.0
        if effect.kind == EFFECT_TRIANGLE:
            return 1.0 - 4.0 * abs(phase - 0.5)
        if effect.kind == EFFECT_SAW_UP:
            return -1.0 + 2.0 * phase
        if effect.kind == EFFECT_SAW_DOWN:
            return 1.0 - 2.0 * phase
        return 0.0

    def _condition(self, effect: Effect, kinematics: WheelKinematics) -> float:
        if effect.kind == EFFECT_SPRING:
            metric = kinematics.position * DI_MAX
        elif effect.kind == EFFECT_DAMPER:
            # One complete normalized travel per second maps to about half scale.
            metric = clamp(kinematics.velocity * 5_000.0, -DI_MAX, DI_MAX)
        elif effect.kind == EFFECT_INERTIA:
            metric = clamp(kinematics.acceleration * 800.0, -DI_MAX, DI_MAX)
        else:  # friction: Coulomb-style resistance based on direction of motion.
            if abs(kinematics.velocity) < 0.002:
                return 0.0
            metric = DI_MAX if kinematics.velocity > 0 else -DI_MAX

        displaced = metric - effect.condition_offset
        half_deadband = effect.deadband / 2.0

        if abs(displaced) <= half_deadband:
            return 0.0

        if displaced > 0:
            active = displaced - half_deadband
            coefficient = effect.positive_coefficient
            saturation = effect.positive_saturation
        else:
            active = displaced + half_deadband
            coefficient = effect.negative_coefficient
            saturation = effect.negative_saturation

        level = coefficient * active / DI_MAX
        return clamp(level, -saturation, saturation)
