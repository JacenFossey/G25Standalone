"""Background Logitech G25 service for Windows.

The service is the single hardware owner. Windows continues to provide ordinary
controller input. FFB can arrive from either:

* the registered G25Standalone DirectInput OEM effect driver (TCP 26726), or
* the legacy application-local dinput8 proxy (UDP 26725).

The registered path supports all 12 standard DirectInput effect types. The
legacy proxy remains available for games whose DirectInput implementation does
not behave correctly with an OEM FFB driver.
"""

from __future__ import annotations

import argparse
import signal
import socket
import struct
import sys
import time
from dataclasses import dataclass
from enum import Enum, auto

import hid

from ffb_engine import EffectEngine, WheelKinematics
from ffb_server import FfbServer, HOST as DRIVER_HOST, PORT as DRIVER_PORT

LOGITECH_VID = 0x046D
G25_LEGACY_PID = 0xC294
G25_NATIVE_PID = 0xC299

MIN_RANGE_DEGREES = 40
MAX_RANGE_DEGREES = 900
DEFAULT_RANGE_DEGREES = 900

LEGACY_FFB_HOST = "127.0.0.1"
LEGACY_FFB_PORT = 26725
LEGACY_WATCHDOG_SECONDS = 0.15
MAIN_LOOP_SLEEP_SECONDS = 0.004  # ~250 Hz renderer

DEVICE_POLL_INTERVAL_SECONDS = 0.50
REENUMERATION_TIMEOUT_SECONDS = 8.0
RETRY_INTERVAL_SECONDS = 3.0

G25_FORCE_NEUTRAL_BYTE = 0x80
# Smooth the high-resolution force before converting it to the G25's 8-bit
# hardware command. This avoids turning small game-side changes into coarse,
# gear-like steps while adding only a few milliseconds of settling time.
G25_FORCE_SMOOTHING_ALPHA = 0.35

ENTER_NATIVE_MODE_REPORT = bytes([0x00, 0xF8, 0x10, 0, 0, 0, 0, 0])
STOP_ALL_REPORT = bytes([0x00, 0xF3, 0, 0, 0, 0, 0, 0])
DEFAULT_SPRING_OFF_REPORT = bytes([0x00, 0xF5, 0, 0, 0, 0, 0, 0])


class WheelState(Enum):
    DISCONNECTED = auto()
    LEGACY = auto()
    NATIVE = auto()


@dataclass(frozen=True)
class G25Device:
    state: WheelState
    info: dict | None = None


_running = True


def request_stop(signum=None, frame=None) -> None:
    del signum, frame
    global _running
    _running = False


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a Logitech G25 on modern Windows without Logitech Gaming Software."
    )
    parser.add_argument(
        "--range",
        dest="range_degrees",
        type=int,
        default=DEFAULT_RANGE_DEGREES,
        help=f"steering range in degrees ({MIN_RANGE_DEGREES}-{MAX_RANGE_DEGREES})",
    )
    args = parser.parse_args()
    if not MIN_RANGE_DEGREES <= args.range_degrees <= MAX_RANGE_DEGREES:
        parser.error(
            f"--range must be between {MIN_RANGE_DEGREES} and {MAX_RANGE_DEGREES} degrees"
        )
    return args


def find_hid_device(product_id: int) -> dict | None:
    devices = hid.enumerate(LOGITECH_VID, product_id)
    return devices[0] if devices else None


def detect_g25() -> G25Device:
    native = find_hid_device(G25_NATIVE_PID)
    if native is not None:
        return G25Device(WheelState.NATIVE, native)
    legacy = find_hid_device(G25_LEGACY_PID)
    if legacy is not None:
        return G25Device(WheelState.LEGACY, legacy)
    return G25Device(WheelState.DISCONNECTED)


def make_range_report(degrees: int) -> bytes:
    return bytes([0x00, 0xF8, 0x81, degrees & 0xFF, (degrees >> 8) & 0xFF, 0, 0, 0])


def force_to_wheel_byte(magnitude: int) -> int:
    magnitude = clamp(magnitude, -10000, 10000)
    return clamp(round(G25_FORCE_NEUTRAL_BYTE + (magnitude / 10000.0) * 0x7F), 0x01, 0xFF)


def make_force_report_byte(force_byte: int) -> bytes:
    # Logitech lg4ff constant-force slot 0.
    return bytes([0x00, 0x11, 0x08, clamp(force_byte, 0x01, 0xFF), 0x80, 0, 0, 0])


def make_force_report(magnitude: int) -> bytes:
    return make_force_report_byte(force_to_wheel_byte(magnitude))


def send_report_once(device_info: dict, report: bytes) -> int:
    device = hid.device()
    try:
        device.open_path(device_info["path"])
        return device.write(report)
    finally:
        try:
            device.close()
        except Exception:
            pass


def switch_to_native_mode(device_info: dict) -> bool:
    try:
        written = send_report_once(device_info, ENTER_NATIVE_MODE_REPORT)
        if written <= 0:
            print("[G25] Native-mode command was not accepted.")
            return False
        print(f"[G25] Sent native-mode command ({written} bytes).")
    except OSError as exc:
        # Re-enumeration can invalidate the old handle immediately after success.
        print(f"[G25] C294 handle changed during mode switch: {exc}")

    print("[G25] Waiting for C299 native mode...")
    deadline = time.monotonic() + REENUMERATION_TIMEOUT_SECONDS
    while _running and time.monotonic() < deadline:
        if find_hid_device(G25_NATIVE_PID) is not None:
            print("[G25] Native mode ready: 046D:C299.")
            return True
        time.sleep(0.20)
    print("[G25] Timed out waiting for C299.")
    return False


class G25Output:
    def __init__(self) -> None:
        self.device = None
        self.path = None
        self.current_force_byte = G25_FORCE_NEUTRAL_BYTE
        self.filtered_force = 0.0

    @property
    def connected(self) -> bool:
        return self.device is not None

    def _write(self, report: bytes) -> None:
        if self.device is None:
            raise OSError("G25 output device is not open")
        written = self.device.write(report)
        if written <= 0:
            raise OSError("G25 HID write failed")

    def open(self, device_info: dict, range_degrees: int) -> None:
        self.close(send_stop=False)
        device = hid.device()
        try:
            device.open_path(device_info["path"])
            device.set_nonblocking(1)
            self.device = device
            self.path = device_info["path"]
            self._write(make_range_report(range_degrees))
            print(f"[G25] Steering range set to {range_degrees}°.")
            self._write(STOP_ALL_REPORT)
            self._write(DEFAULT_SPRING_OFF_REPORT)
            self._write(make_force_report_byte(G25_FORCE_NEUTRAL_BYTE))
            self.current_force_byte = G25_FORCE_NEUTRAL_BYTE
            self.filtered_force = 0.0
            print("[G25] Force-feedback output ready.")
        except Exception:
            try:
                device.close()
            except Exception:
                pass
            self.device = None
            self.path = None
            raise

    def set_force(self, magnitude: int, *, immediate: bool = False) -> None:
        """Apply a short low-pass filter before G25 force quantization.

        The registered driver can update/render more frequently than the old
        application-local proxy. Directly quantizing every small change to the
        G25's 8-bit constant-force command can feel like the gear train is
        stepping under sustained load. Filtering in the original DirectInput
        range keeps those transitions continuous before they hit the coarse
        hardware command.

        Safety/lifecycle neutralization bypasses the filter so a stopped game or
        disabled actuator returns to zero immediately.
        """
        magnitude = clamp(magnitude, -10000, 10000)

        if immediate:
            self.filtered_force = float(magnitude)
        else:
            self.filtered_force += (
                magnitude - self.filtered_force
            ) * G25_FORCE_SMOOTHING_ALPHA

        target_force_byte = force_to_wheel_byte(round(self.filtered_force))
        if target_force_byte == self.current_force_byte:
            return

        self._write(make_force_report_byte(target_force_byte))
        self.current_force_byte = target_force_byte

    def read_steering(self) -> int | None:
        if self.device is None:
            return None
        data = self.device.read(64)
        latest = None
        while data:
            # C299 native report: steering is a 14-bit value across bytes 3/4.
            if len(data) >= 5:
                latest = ((data[3] >> 2) & 0x3F) | (data[4] << 6)
            data = self.device.read(64)
        return latest

    def close(self, *, send_stop: bool = True) -> None:
        if self.device is None:
            return
        if send_stop:
            try:
                self._write(make_force_report_byte(G25_FORCE_NEUTRAL_BYTE))
                self._write(STOP_ALL_REPORT)
            except Exception:
                pass
        try:
            self.device.close()
        except Exception:
            pass
        self.device = None
        self.path = None
        self.current_force_byte = G25_FORCE_NEUTRAL_BYTE
        self.filtered_force = 0.0


def create_legacy_ffb_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LEGACY_FFB_HOST, LEGACY_FFB_PORT))
    sock.setblocking(False)
    return sock


def receive_latest_legacy_force(sock: socket.socket) -> int | None:
    latest = None
    while True:
        try:
            data, _ = sock.recvfrom(64)
        except BlockingIOError:
            break
        if len(data) == 4:
            latest = struct.unpack("!i", data)[0]
    return None if latest is None else clamp(latest, -10000, 10000)


def main() -> int:
    args = parse_args()
    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    try:
        legacy_socket = create_legacy_ffb_socket()
    except OSError as exc:
        print(
            f"Could not bind legacy FFB UDP {LEGACY_FFB_HOST}:{LEGACY_FFB_PORT}: {exc}",
            file=sys.stderr,
        )
        return 1

    engine = EffectEngine()
    try:
        driver_server = FfbServer(engine)
    except OSError as exc:
        legacy_socket.close()
        print(
            f"Could not bind DirectInput driver IPC {DRIVER_HOST}:{DRIVER_PORT}: {exc}",
            file=sys.stderr,
        )
        return 1

    kinematics = WheelKinematics()
    output = G25Output()

    print("G25Standalone — G25 service")
    print("---------------------------")
    print(f"Steering range: {args.range_degrees}°")
    print(f"Registered DirectInput driver: {DRIVER_HOST}:{DRIVER_PORT}")
    print(f"Legacy dinput8 proxy: {LEGACY_FFB_HOST}:{LEGACY_FFB_PORT}")
    print("Watching for Logitech G25. Press Ctrl+C to stop.")
    print()

    last_state = None
    next_device_poll = 0.0
    retry_after = 0.0
    legacy_force = 0
    legacy_force_at = 0.0

    try:
        while _running:
            now = time.monotonic()

            # Process lifecycle/effect messages from all game processes.
            driver_server.poll()

            incoming_legacy = receive_latest_legacy_force(legacy_socket)
            if incoming_legacy is not None:
                legacy_force = incoming_legacy
                legacy_force_at = now

            if output.connected:
                try:
                    steering = output.read_steering()
                    if steering is not None:
                        kinematics.update_raw(steering, now)

                    # A registered driver connection has priority. This makes it
                    # safe to leave an old local proxy file around while testing.
                    force_active = False
                    if engine.sessions:
                        desired_force = engine.render(kinematics, now)
                        force_active = engine.has_active_effects()
                    elif now - legacy_force_at <= LEGACY_WATCHDOG_SECONDS:
                        desired_force = legacy_force
                        force_active = True
                    else:
                        desired_force = 0

                    output.set_force(desired_force, immediate=not force_active)
                except OSError as exc:
                    print(f"[G25] Runtime HID failure: {exc}", file=sys.stderr)
                    output.close(send_stop=False)
                    next_device_poll = 0.0

            if now >= next_device_poll:
                next_device_poll = now + DEVICE_POLL_INTERVAL_SECONDS
                try:
                    detected = detect_g25()
                except Exception as exc:
                    print(f"[G25] Detection error: {exc}", file=sys.stderr)
                    detected = G25Device(WheelState.DISCONNECTED)

                if detected.state != last_state:
                    if detected.state is WheelState.DISCONNECTED:
                        print("[G25] Disconnected. Waiting...")
                    elif detected.state is WheelState.LEGACY:
                        print("[G25] Connected in compatibility mode: 046D:C294.")
                    else:
                        print("[G25] Connected in native mode: 046D:C299.")
                    last_state = detected.state

                if detected.state is WheelState.DISCONNECTED:
                    output.close(send_stop=False)
                elif detected.state is WheelState.LEGACY:
                    output.close(send_stop=False)
                    if now >= retry_after:
                        if switch_to_native_mode(detected.info or {}):
                            next_device_poll = 0.0
                        else:
                            retry_after = time.monotonic() + RETRY_INTERVAL_SECONDS
                else:
                    info = detected.info or {}
                    current_path = info.get("path")
                    needs_open = not output.connected or output.path != current_path
                    if needs_open and now >= retry_after:
                        try:
                            output.open(info, args.range_degrees)
                            print("[G25] Ready.")
                        except OSError as exc:
                            print(f"[G25] Could not initialize native output: {exc}", file=sys.stderr)
                            output.close(send_stop=False)
                            retry_after = time.monotonic() + RETRY_INTERVAL_SECONDS

            time.sleep(MAIN_LOOP_SLEEP_SECONDS)

    except KeyboardInterrupt:
        request_stop()
    finally:
        print("\n[G25] Neutralizing force...")
        output.close(send_stop=True)
        driver_server.close()
        legacy_socket.close()

    print("G25Standalone stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
