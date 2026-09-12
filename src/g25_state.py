from __future__ import annotations

import hid


VID = 0x046D
PID = 0xC299


def decode(report: bytes):
    if len(report) < 11:
        return None

    # Low nibble is POV/hat.
    # 0-7 = direction, 8 = neutral.
    hat = report[0] & 0x0F

    # G25 exposes 19 button bits.
    buttons_raw = (
        (report[0] >> 4)
        | (report[1] << 4)
        | (report[2] << 12)
    ) & ((1 << 19) - 1)

    buttons = [
        i + 1
        for i in range(19)
        if buttons_raw & (1 << i)
    ]

    # 14-bit steering:
    # lower 6 bits are bits 2-7 of byte 3,
    # upper 8 bits are byte 4.
    steering = (
        ((report[3] >> 2) & 0x3F)
        | (report[4] << 6)
    )

    # These appear to be the three pedal axes.
    # We'll verify their exact order experimentally.
    pedal_a = report[5]
    pedal_b = report[6]
    pedal_c = report[7]

    vendor = report[8:11]

    return {
        "hat": hat,
        "buttons": buttons,
        "steering": steering,
        "pedal_a": pedal_a,
        "pedal_b": pedal_b,
        "pedal_c": pedal_c,
        "vendor": vendor,
    }


def main():
    device = hid.device()

    try:
        device.open(VID, PID)
    except OSError:
        print("G25 native device 046D:C299 not found.")
        return

    print("G25Standalone — native input state")
    print("----------------------------------")
    print("Press Ctrl+C to stop.")
    print()

    last = None

    try:
        while True:
            data = device.read(64)

            if not data:
                continue

            report = bytes(data)

            if report == last:
                continue

            last = report
            state = decode(report)

            if state is None:
                continue

            vendor = " ".join(
                f"{b:02X}"
                for b in state["vendor"]
            )

            print(
                f"steer={state['steering']:5d}  "
                f"A={state['pedal_a']:3d}  "
                f"B={state['pedal_b']:3d}  "
                f"C={state['pedal_c']:3d}  "
                f"hat={state['hat']}  "
                f"buttons={state['buttons']}  "
                f"vendor={vendor}"
            )

    except KeyboardInterrupt:
        print("\nStopped.")

    finally:
        device.close()


if __name__ == "__main__":
    main()
