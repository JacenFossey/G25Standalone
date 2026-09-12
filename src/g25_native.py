"""Switch Logitech G25 from compatibility mode to native mode."""

from __future__ import annotations

import time
import hid


LOGITECH_VID = 0x046D
LEGACY_PID = 0xC294
NATIVE_PID = 0xC299

# HIDAPI requires report ID 0 as the first byte.
ENTER_NATIVE_MODE = bytes([
    0x00,
    0xF8, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00,
])


def find_device(pid: int):
    devices = hid.enumerate(LOGITECH_VID, pid)
    return devices[0] if devices else None


def main():
    print("G25Standalone — native mode switch")
    print("----------------------------------")

    native = find_device(NATIVE_PID)

    if native:
        print("G25 is already in native mode: 046D:C299")
        return

    legacy = find_device(LEGACY_PID)

    if not legacy:
        print("No G25 found as C294 or C299.")
        return

    print("Found G25 in compatibility mode: 046D:C294")
    print("Sending native-mode command...")

    device = hid.device()

    try:
        device.open_path(legacy["path"])

        try:
            written = device.write(ENTER_NATIVE_MODE)
            print(f"Write returned {written} bytes.")
        except OSError as exc:
            # The wheel may disappear immediately because changing mode
            # causes it to reconnect with another USB product ID.
            print(f"Device disconnected during command: {exc}")

    finally:
        try:
            device.close()
        except Exception:
            pass

    print("Waiting for G25 to re-enumerate...")

    deadline = time.monotonic() + 8

    while time.monotonic() < deadline:
        native = find_device(NATIVE_PID)

        if native:
            print()
            print("SUCCESS")
            print("G25 is now in native mode: 046D:C299")
            return

        time.sleep(0.25)

    print()
    print("G25 did not appear as C299.")


if __name__ == "__main__":
    main()
