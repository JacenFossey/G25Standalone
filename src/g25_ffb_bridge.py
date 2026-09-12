from __future__ import annotations

import select
import socket
import struct
import time

import hid


LOGITECH_VID = 0x046D
G25_NATIVE_PID = 0xC299

HOST = "127.0.0.1"
PORT = 26725

# If the game/proxy disappears while torque is active,
# neutralize the wheel quickly.
WATCHDOG_SECONDS = 0.15


def find_g25() -> dict | None:
    devices = hid.enumerate(LOGITECH_VID, G25_NATIVE_PID)
    return devices[0] if devices else None


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def force_to_wheel_byte(magnitude: int) -> int:
    """
    DirectInput constant force:
        -10000 ... 0 ... +10000

    Logitech lg4ff:
        0x01 ... 0x80 ... 0xFF
    """
    magnitude = clamp(magnitude, -10000, 10000)

    normalized = magnitude / 10000.0

    value = round(
        0x80 + normalized * 0x7F
    )

    return clamp(value, 0x01, 0xFF)


def make_force_report(magnitude: int) -> bytes:
    force = force_to_wheel_byte(magnitude)

    # lg4ff Constant Force:
    #   11 08 <force> 80 00 00 00
    return bytes([
        0x00,       # HID report ID
        0x11,
        0x08,
        force,
        0x80,
        0x00,
        0x00,
        0x00,
    ])

DEFAULT_SPRING_OFF_REPORT = bytes([
    0x00,
    0xF5,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
])
STOP_REPORT = bytes([
    0x00,
    0xF3,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
])


def main() -> int:
    info = find_g25()

    if info is None:
        print("Native G25 046D:C299 not found.")
        print("Run g25_service.py first.")
        return 1

    wheel = hid.device()

    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM,
    )

    sock.bind((HOST, PORT))
    sock.setblocking(False)

    wheel.open_path(info["path"])

    print("G25Standalone — FFB bridge")
    print("--------------------------")
    print(f"Listening on {HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    print()

    current_force = 0
    last_packet = time.monotonic()

    try:
        # Clear anything left over from a previous session.
        wheel.write(STOP_REPORT)

        # Disable the G25's built-in/default centering spring.
        # The game should provide steering forces itself.
        wheel.write(DEFAULT_SPRING_OFF_REPORT)

        # Known neutral constant-force state.
        wheel.write(make_force_report(0))

        print("Default centering spring disabled.")

        while True:
            ready, _, _ = select.select(
                [sock],
                [],
                [],
                0.02,
            )

            if ready:
                # Drain the UDP queue and use only the newest
                # force sample. Old force samples are worthless.
                latest: bytes | None = None

                while True:
                    try:
                        data, _ = sock.recvfrom(64)
                        latest = data

                    except BlockingIOError:
                        break

                if latest is not None and len(latest) == 4:
                    magnitude = struct.unpack(
                        "!i",
                        latest,
                    )[0]

                    magnitude = clamp(
                        magnitude,
                        -10000,
                        10000,
                    )

                    current_force = magnitude
                    last_packet = time.monotonic()

                    wheel.write(
                        make_force_report(magnitude)
                    )

            # Safety watchdog.
            if (
                current_force != 0
                and time.monotonic() - last_packet
                > WATCHDOG_SECONDS
            ):
                current_force = 0

                wheel.write(
                    make_force_report(0)
                )

    except KeyboardInterrupt:
        pass

    finally:
        try:
            wheel.write(make_force_report(0))
            wheel.write(STOP_REPORT)
        except Exception:
            pass

        try:
            wheel.close()
        except Exception:
            pass

        sock.close()

    print("FFB bridge stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
