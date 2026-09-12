"""Background Logitech G25 initializer for Windows.

G25Standalone milestone 0.2b

Behavior:
- waits for a Logitech G25 to be connected;
- if it appears as C294 compatibility mode, switches it to C299 native mode;
- once C299 is available, configures the requested steering range;
- continues running so unplug/replug cycles are handled automatically.

Windows itself handles steering, pedals, clutch, H-shifter, buttons, and POV
through its built-in HID / DirectInput stack once the G25 is in native mode.

This version intentionally does NOT:
- provide force feedback;
- install a custom driver;
- create a virtual controller.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from dataclasses import dataclass
from enum import Enum, auto

import hid


LOGITECH_VID = 0x046D
G25_LEGACY_PID = 0xC294
G25_NATIVE_PID = 0xC299

MIN_RANGE_DEGREES = 40
MAX_RANGE_DEGREES = 900
DEFAULT_RANGE_DEGREES = 900

# hidapi on Windows expects report ID 0x00 as the first byte.
#
# Logitech G25 compatibility -> native command:
#   F8 10 00 00 00 00 00
ENTER_NATIVE_MODE_REPORT = bytes(
    [0x00, 0xF8, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00]
)

POLL_INTERVAL_SECONDS = 0.50
REENUMERATION_TIMEOUT_SECONDS = 8.0


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
    global _running
    _running = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize a Logitech G25 on Windows without Logitech Gaming Software."
    )
    parser.add_argument(
        "--range",
        dest="range_degrees",
        type=int,
        default=DEFAULT_RANGE_DEGREES,
        help=f"steering range in degrees ({MIN_RANGE_DEGREES}-{MAX_RANGE_DEGREES}, "
             f"default: {DEFAULT_RANGE_DEGREES})",
    )

    args = parser.parse_args()

    if not MIN_RANGE_DEGREES <= args.range_degrees <= MAX_RANGE_DEGREES:
        parser.error(
            f"--range must be between {MIN_RANGE_DEGREES} "
            f"and {MAX_RANGE_DEGREES} degrees"
        )

    return args


def find_hid_device(product_id: int) -> dict | None:
    """Return the first matching G25 HID interface, if present."""
    devices = hid.enumerate(LOGITECH_VID, product_id)
    return devices[0] if devices else None


def detect_g25() -> G25Device:
    """Determine whether the wheel is disconnected, C294, or C299."""
    native = find_hid_device(G25_NATIVE_PID)
    if native is not None:
        return G25Device(WheelState.NATIVE, native)

    legacy = find_hid_device(G25_LEGACY_PID)
    if legacy is not None:
        return G25Device(WheelState.LEGACY, legacy)

    return G25Device(WheelState.DISCONNECTED)


def make_range_report(degrees: int) -> bytes:
    """Build the Logitech G25 native steering-range HID output report."""
    low = degrees & 0xFF
    high = (degrees >> 8) & 0xFF

    # Logitech payload:
    #   F8 81 <low> <high> 00 00 00
    return bytes([
        0x00,
        0xF8,
        0x81,
        low,
        high,
        0x00,
        0x00,
        0x00,
    ])


def send_report(device_info: dict, report: bytes) -> int:
    """Open a HID path, send one output report, then close it."""
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
    """Send the G25 compatibility -> native mode command."""
    try:
        try:
            written = send_report(device_info, ENTER_NATIVE_MODE_REPORT)

            if written <= 0:
                print("[G25] Native-mode command was not accepted.")
                return False

            print(f"[G25] Sent native-mode command ({written} bytes).")

        except OSError as exc:
            # A successful switch can invalidate the C294 handle immediately
            # because the wheel detaches and re-enumerates as C299.
            print(f"[G25] C294 handle changed during mode switch: {exc}")

    except OSError as exc:
        print(f"[G25] Could not open C294 device: {exc}")
        return False

    print("[G25] Waiting for C299 native mode...")

    deadline = time.monotonic() + REENUMERATION_TIMEOUT_SECONDS

    while _running and time.monotonic() < deadline:
        if find_hid_device(G25_NATIVE_PID) is not None:
            print("[G25] Native mode ready: 046D:C299.")
            return True

        time.sleep(0.20)

    print("[G25] Timed out waiting for C299.")
    return False


def set_rotation_range(device_info: dict, degrees: int) -> bool:
    """Configure the native G25's logical steering range."""
    report = make_range_report(degrees)

    try:
        written = send_report(device_info, report)

        if written <= 0:
            print("[G25] Steering-range command was not accepted.")
            return False

        command_hex = " ".join(f"{byte:02X}" for byte in report[1:])
        print(f"[G25] Steering range set to {degrees}°.")
        print(f"[G25] Range command: {command_hex}")
        return True

    except OSError as exc:
        print(f"[G25] Failed to set steering range: {exc}")
        return False


def main() -> int:
    args = parse_args()

    signal.signal(signal.SIGINT, request_stop)

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    print("G25Standalone — background G25 initializer")
    print("------------------------------------------")
    print(f"Configured steering range: {args.range_degrees}°")
    print("Watching for Logitech G25.")
    print("Press Ctrl+C to stop.")
    print()

    last_state: WheelState | None = None
    retry_after = 0.0

    # We only need to apply range once per native-mode connection.
    range_configured = False

    while _running:
        try:
            detected = detect_g25()

            if detected.state != last_state:
                if detected.state is WheelState.DISCONNECTED:
                    print("[G25] Disconnected. Waiting...")
                    range_configured = False

                elif detected.state is WheelState.LEGACY:
                    print("[G25] Connected in compatibility mode: 046D:C294.")
                    range_configured = False

                elif detected.state is WheelState.NATIVE:
                    print("[G25] Connected in native mode: 046D:C299.")

                last_state = detected.state

            if detected.state is WheelState.LEGACY:
                now = time.monotonic()

                # Avoid hammering the wheel if a switch attempt fails.
                if now >= retry_after:
                    success = switch_to_native_mode(detected.info or {})

                    if success:
                        last_state = WheelState.NATIVE
                        range_configured = False
                    else:
                        retry_after = time.monotonic() + 3.0

            elif detected.state is WheelState.NATIVE and not range_configured:
                success = set_rotation_range(
                    detected.info or {},
                    args.range_degrees,
                )

                if success:
                    range_configured = True
                    print("[G25] Ready.")
                else:
                    retry_after = time.monotonic() + 3.0

            time.sleep(POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            request_stop()

        except Exception as exc:
            # Keep the watcher alive across transient USB/HID errors.
            print(f"[G25] Unexpected HID error: {exc}", file=sys.stderr)
            time.sleep(1.0)

    print()
    print("G25Standalone stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
