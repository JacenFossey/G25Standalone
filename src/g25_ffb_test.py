from __future__ import annotations

import time

import hid


VID = 0x046D
PID = 0xC299


def find_g25():
    devices = hid.enumerate(VID, PID)
    return devices[0] if devices else None


def write_report(device, payload: list[int]):
    report = bytes([0x00] + payload)

    written = device.write(report)

    print(
        f"sent {written} bytes: "
        + " ".join(f"{b:02X}" for b in payload)
    )


def constant_force(force_byte: int) -> list[int]:
    """
    Logitech lg4ff constant-force command.

    0x80 = neutral
    below/above 0x80 = opposite directions
    """
    return [
        0x11,
        0x08,
        force_byte,
        0x80,
        0x00,
        0x00,
        0x00,
    ]


def stop_all() -> list[int]:
    return [
        0xF3,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
    ]


def main():
    info = find_g25()

    if info is None:
        print("Native G25 046D:C299 not found.")
        print("Run g25_service.py first.")
        return

    device = hid.device()

    try:
        device.open_path(info["path"])

        print("G25Standalone — direct FFB test")
        print("--------------------------------")
        print()
        print("The wheel may apply torque.")
        print("Keep your hands lightly on the wheel.")
        print()

        # Start from a known safe state.
        write_report(device, stop_all())
        time.sleep(0.5)

        # Neutral.
        write_report(device, constant_force(0x80))
        time.sleep(0.5)

        print("Applying gentle force in one direction...")
        write_report(device, constant_force(0x98))
        time.sleep(1.5)

        print("Returning to neutral...")
        write_report(device, constant_force(0x80))
        time.sleep(1.0)

        print("Applying gentle force in the opposite direction...")
        write_report(device, constant_force(0x68))
        time.sleep(1.5)

        print("Returning to neutral...")
        write_report(device, constant_force(0x80))
        time.sleep(0.5)

        write_report(device, stop_all())

        print()
        print("Test complete.")

    finally:
        try:
            # Fail-safe: always try to remove torque.
            write_report(device, constant_force(0x80))
            write_report(device, stop_all())
        except Exception:
            pass

        device.close()


if __name__ == "__main__":
    main()
