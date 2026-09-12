"""Background G25 native-mode watcher for Windows.

G25Standalone milestone 0.2a

Behavior:
- waits for a Logitech G25 to be connected;
- if it appears as C294 compatibility mode, sends the documented native-mode
  command and waits for C299 to re-enumerate;
- if it is already C299, leaves it alone;
- continues running so unplug/replug cycles are handled automatically.

This version intentionally does NOT:
- configure steering range;
- send force-feedback commands;
- install a driver;
- create a virtual controller.
"""

from __future__ import annotations

import signal
import sys
import time
from dataclasses import dataclass
from enum import Enum, auto

import hid


LOGITECH_VID = 0x046D
G25_LEGACY_PID = 0xC294
G25_NATIVE_PID = 0xC299

# hidapi on Windows expects report ID 0x00 as the first byte.
# Actual Logitech G25 command payload:
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


def switch_to_native_mode(device_info: dict) -> bool:
    """Send the one known G25 compatibility -> native mode command."""
    device = hid.device()

    try:
        device.open_path(device_info["path"])

        try:
            written = device.write(ENTER_NATIVE_MODE_REPORT)

            if written <= 0:
                print("[G25] Native-mode command was not accepted.")
                return False

            print(f"[G25] Sent native-mode command ({written} bytes).")

        except OSError as exc:
            # A successful switch can make the C294 USB device vanish
            # immediately, invalidating the handle during/after the write.
            # We still wait for C299 before deciding that the operation failed.
            print(f"[G25] C294 handle changed during mode switch: {exc}")

    except OSError as exc:
        print(f"[G25] Could not open C294 device: {exc}")
        return False

    finally:
        try:
            device.close()
        except Exception:
            pass

    print("[G25] Waiting for C299 native mode...")

    deadline = time.monotonic() + REENUMERATION_TIMEOUT_SECONDS

    while _running and time.monotonic() < deadline:
        if find_hid_device(G25_NATIVE_PID) is not None:
            print("[G25] Native mode ready: 046D:C299.")
            return True

        time.sleep(0.20)

    print("[G25] Timed out waiting for C299.")
    return False


def main() -> int:
    signal.signal(signal.SIGINT, request_stop)

    # SIGTERM exists on Windows Python as well, though console behavior differs.
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    print("G25Standalone — background native-mode watcher")
    print("-----------------------------------------------")
    print("Watching for Logitech G25.")
    print("Press Ctrl+C to stop.")
    print()

    last_state: WheelState | None = None
    retry_after = 0.0

    while _running:
        try:
            detected = detect_g25()

            if detected.state != last_state:
                if detected.state is WheelState.DISCONNECTED:
                    print("[G25] Disconnected. Waiting...")
                elif detected.state is WheelState.LEGACY:
                    print("[G25] Connected in compatibility mode: 046D:C294.")
                elif detected.state is WheelState.NATIVE:
                    print("[G25] Connected in native mode: 046D:C299. Ready.")

                last_state = detected.state

            if detected.state is WheelState.LEGACY:
                now = time.monotonic()

                # Avoid hammering a device if a switch attempt fails.
                if now >= retry_after:
                    success = switch_to_native_mode(detected.info or {})

                    if success:
                        last_state = WheelState.NATIVE
                    else:
                        retry_after = time.monotonic() + 3.0

            time.sleep(POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            request_stop()

        except Exception as exc:
            # Keep the watcher alive across transient HID/USB errors.
            print(f"[G25] Unexpected HID error: {exc}", file=sys.stderr)
            time.sleep(1.0)

    print()
    print("G25Standalone stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
