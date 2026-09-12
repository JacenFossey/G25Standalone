"""Set Logitech G25 steering rotation range in native C299 mode.

Usage:
    python g25_range.py
    python g25_range.py 900
    python g25_range.py 540

The G25 must already be in native mode (USB PID 046D:C299).

Known Logitech command:
    F8 81 <range low byte> <range high byte> 00 00 00

hidapi on Windows requires report ID 0x00 before the seven-byte payload.
"""

from __future__ import annotations

import argparse
import sys

import hid


LOGITECH_VID = 0x046D
G25_NATIVE_PID = 0xC299

MIN_RANGE_DEGREES = 40
MAX_RANGE_DEGREES = 900


def find_native_g25() -> dict | None:
    devices = hid.enumerate(LOGITECH_VID, G25_NATIVE_PID)
    return devices[0] if devices else None


def make_range_report(degrees: int) -> bytes:
    if not MIN_RANGE_DEGREES <= degrees <= MAX_RANGE_DEGREES:
        raise ValueError(
            f"Rotation range must be between "
            f"{MIN_RANGE_DEGREES} and {MAX_RANGE_DEGREES} degrees."
        )

    low = degrees & 0xFF
    high = (degrees >> 8) & 0xFF

    # HID report ID 0 followed by the seven-byte Logitech payload.
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


def set_rotation_range(device_info: dict, degrees: int) -> bool:
    report = make_range_report(degrees)

    device = hid.device()

    try:
        device.open_path(device_info["path"])
        written = device.write(report)

        if written <= 0:
            print("[G25] Range command was not accepted.", file=sys.stderr)
            return False

        print(f"[G25] Sent {written} bytes.")
        print(
            "[G25] Command: "
            + " ".join(f"{byte:02X}" for byte in report[1:])
        )
        return True

    except OSError as exc:
        print(f"[G25] Failed to send range command: {exc}", file=sys.stderr)
        return False

    finally:
        try:
            device.close()
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set Logitech G25 steering rotation range."
    )
    parser.add_argument(
        "degrees",
        nargs="?",
        type=int,
        default=900,
        help="steering range in degrees (40-900, default: 900)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not MIN_RANGE_DEGREES <= args.degrees <= MAX_RANGE_DEGREES:
        print(
            f"Range must be between "
            f"{MIN_RANGE_DEGREES} and {MAX_RANGE_DEGREES} degrees.",
            file=sys.stderr,
        )
        return 2

    print("G25Standalone — steering range test")
    print("-----------------------------------")
    print(f"Requested range: {args.degrees}°")

    g25 = find_native_g25()

    if g25 is None:
        print()
        print("Native G25 (046D:C299) not found.", file=sys.stderr)
        print(
            "Run g25_service.py or g25_native.py first, then retry.",
            file=sys.stderr,
        )
        return 3

    print("Native G25 found: 046D:C299")

    if not set_rotation_range(g25, args.degrees):
        return 4

    print(f"[G25] Requested steering range: {args.degrees}°")
    print()
    print("Turn the wheel gently lock-to-lock and verify the physical range.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
