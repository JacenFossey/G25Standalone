"""Background Logitech G25 service for Windows.

Responsibilities:
- detect the Logitech G25;
- switch C294 compatibility mode -> C299 native mode;
- configure steering range;
- disable the wheel's built-in/default centering spring;
- receive DirectInput constant-force commands from the dinput8 proxy over UDP;
- translate those forces to Logitech lg4ff HID reports;
- neutralize force if the game/proxy disappears;
- survive unplug/replug cycles.

Windows continues to handle normal controller input through its built-in
HID / DirectInput stack.
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


# ---------------------------------------------------------------------------
# G25 USB identity
# ---------------------------------------------------------------------------

LOGITECH_VID = 0x046D
G25_LEGACY_PID = 0xC294
G25_NATIVE_PID = 0xC299


# ---------------------------------------------------------------------------
# Steering range
# ---------------------------------------------------------------------------

MIN_RANGE_DEGREES = 40
MAX_RANGE_DEGREES = 900
DEFAULT_RANGE_DEGREES = 900


# ---------------------------------------------------------------------------
# FFB bridge
# ---------------------------------------------------------------------------

FFB_HOST = "127.0.0.1"
FFB_PORT = 26725

# If the game or proxy disappears while torque is active, return to neutral.
FFB_WATCHDOG_SECONDS = 0.15

# Run the force-output loop at up to ~200 Hz.
MAIN_LOOP_SLEEP_SECONDS = 0.005


# ---------------------------------------------------------------------------
# Device watcher
# ---------------------------------------------------------------------------

DEVICE_POLL_INTERVAL_SECONDS = 0.50
REENUMERATION_TIMEOUT_SECONDS = 8.0
RETRY_INTERVAL_SECONDS = 3.0


# ---------------------------------------------------------------------------
# Logitech HID reports
#
# hidapi on Windows expects report ID 0x00 as the first byte.
# ---------------------------------------------------------------------------

# Compatibility mode -> native G25 mode:
#
#   F8 10 00 00 00 00 00
ENTER_NATIVE_MODE_REPORT = bytes([
    0x00,
    0xF8,
    0x10,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
])


# Stop all Logitech FFB effects:
#
#   F3 00 00 00 00 00 00
STOP_ALL_REPORT = bytes([
    0x00,
    0xF3,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
])


# Disable built-in/default centering spring:
#
#   F5 00 00 00 00 00 00
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


class WheelState(Enum):
    DISCONNECTED = auto()
    LEGACY = auto()
    NATIVE = auto()


@dataclass(frozen=True)
class G25Device:
    state: WheelState
    info: dict | None = None


_running = True


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def request_stop(signum=None, frame=None) -> None:
    global _running
    _running = False


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Logitech G25 on modern Windows without Logitech "
            "Gaming Software."
        )
    )

    parser.add_argument(
        "--range",
        dest="range_degrees",
        type=int,
        default=DEFAULT_RANGE_DEGREES,
        help=(
            f"steering range in degrees "
            f"({MIN_RANGE_DEGREES}-{MAX_RANGE_DEGREES}, "
            f"default: {DEFAULT_RANGE_DEGREES})"
        ),
    )

    args = parser.parse_args()

    if not MIN_RANGE_DEGREES <= args.range_degrees <= MAX_RANGE_DEGREES:
        parser.error(
            f"--range must be between "
            f"{MIN_RANGE_DEGREES} and {MAX_RANGE_DEGREES} degrees"
        )

    return args


# ---------------------------------------------------------------------------
# Device detection
# ---------------------------------------------------------------------------

def find_hid_device(product_id: int) -> dict | None:
    devices = hid.enumerate(LOGITECH_VID, product_id)
    return devices[0] if devices else None


def detect_g25() -> G25Device:
    native = find_hid_device(G25_NATIVE_PID)

    if native is not None:
        return G25Device(
            WheelState.NATIVE,
            native,
        )

    legacy = find_hid_device(G25_LEGACY_PID)

    if legacy is not None:
        return G25Device(
            WheelState.LEGACY,
            legacy,
        )

    return G25Device(WheelState.DISCONNECTED)


# ---------------------------------------------------------------------------
# Logitech reports
# ---------------------------------------------------------------------------

def make_range_report(degrees: int) -> bytes:
    low = degrees & 0xFF
    high = (degrees >> 8) & 0xFF

    # Logitech payload:
    #
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


def force_to_wheel_byte(magnitude: int) -> int:
    """Convert DirectInput -10000..+10000 to Logitech 0x01..0xFF."""

    magnitude = clamp(
        magnitude,
        -10000,
        10000,
    )

    normalized = magnitude / 10000.0

    value = round(
        0x80 + normalized * 0x7F
    )

    return clamp(
        value,
        0x01,
        0xFF,
    )


def make_force_report(magnitude: int) -> bytes:
    """Build Logitech constant-force report."""

    force = force_to_wheel_byte(magnitude)

    # Logitech lg4ff:
    #
    #   11 08 <force> 80 00 00 00
    return bytes([
        0x00,
        0x11,
        0x08,
        force,
        0x80,
        0x00,
        0x00,
        0x00,
    ])


def send_report_once(
    device_info: dict,
    report: bytes,
) -> int:
    """Open a HID path, send one report, then close it."""

    device = hid.device()

    try:
        device.open_path(device_info["path"])
        return device.write(report)

    finally:
        try:
            device.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Native-mode switching
# ---------------------------------------------------------------------------

def switch_to_native_mode(
    device_info: dict,
) -> bool:
    try:
        written = send_report_once(
            device_info,
            ENTER_NATIVE_MODE_REPORT,
        )

        if written <= 0:
            print(
                "[G25] Native-mode command was not accepted."
            )
            return False

        print(
            f"[G25] Sent native-mode command "
            f"({written} bytes)."
        )

    except OSError as exc:
        # The device may disappear immediately because switching mode
        # causes USB re-enumeration. That can mean the command worked.
        print(
            "[G25] C294 handle changed during mode switch: "
            f"{exc}"
        )

    print(
        "[G25] Waiting for C299 native mode..."
    )

    deadline = (
        time.monotonic()
        + REENUMERATION_TIMEOUT_SECONDS
    )

    while (
        _running
        and time.monotonic() < deadline
    ):
        if find_hid_device(G25_NATIVE_PID) is not None:
            print(
                "[G25] Native mode ready: 046D:C299."
            )
            return True

        time.sleep(0.20)

    print(
        "[G25] Timed out waiting for C299."
    )

    return False


# ---------------------------------------------------------------------------
# Persistent native G25 output session
# ---------------------------------------------------------------------------

class G25Output:
    def __init__(self) -> None:
        self.device = None
        self.path = None

        self.current_force = 0
        self.last_force_packet = time.monotonic()

    @property
    def connected(self) -> bool:
        return self.device is not None

    def _write(
        self,
        report: bytes,
    ) -> None:
        if self.device is None:
            raise OSError(
                "G25 output device is not open"
            )

        written = self.device.write(report)

        if written <= 0:
            raise OSError(
                "G25 HID write failed"
            )

    def open(
        self,
        device_info: dict,
        range_degrees: int,
    ) -> None:
        self.close(send_stop=False)

        device = hid.device()

        try:
            device.open_path(
                device_info["path"]
            )

            self.device = device
            self.path = device_info["path"]

            # Configure logical steering range.
            self._write(
                make_range_report(
                    range_degrees
                )
            )

            print(
                f"[G25] Steering range set to "
                f"{range_degrees}°."
            )

            # Start from a clean FFB state.
            self._write(
                STOP_ALL_REPORT
            )

            # The game should provide steering forces itself.
            self._write(
                DEFAULT_SPRING_OFF_REPORT
            )

            print(
                "[G25] Default centering spring disabled."
            )

            # Explicit neutral constant force.
            self._write(
                make_force_report(0)
            )

            self.current_force = 0
            self.last_force_packet = (
                time.monotonic()
            )

            print(
                "[G25] Force-feedback output ready."
            )

        except Exception:
            try:
                device.close()
            except Exception:
                pass

            self.device = None
            self.path = None

            raise

    def set_force(
        self,
        magnitude: int,
    ) -> None:
        magnitude = clamp(
            magnitude,
            -10000,
            10000,
        )

        # Don't waste USB writes if the force hasn't changed.
        if magnitude != self.current_force:
            self._write(
                make_force_report(magnitude)
            )

            self.current_force = magnitude

        self.last_force_packet = (
            time.monotonic()
        )

    def watchdog(self) -> None:
        if not self.connected:
            return

        if self.current_force == 0:
            return

        elapsed = (
            time.monotonic()
            - self.last_force_packet
        )

        if elapsed > FFB_WATCHDOG_SECONDS:
            self._write(
                make_force_report(0)
            )

            self.current_force = 0

    def close(
        self,
        *,
        send_stop: bool = True,
    ) -> None:
        if self.device is None:
            return

        if send_stop:
            try:
                self._write(
                    make_force_report(0)
                )

                self._write(
                    STOP_ALL_REPORT
                )

            except Exception:
                pass

        try:
            self.device.close()
        except Exception:
            pass

        self.device = None
        self.path = None
        self.current_force = 0


# ---------------------------------------------------------------------------
# UDP FFB input
# ---------------------------------------------------------------------------

def create_ffb_socket() -> socket.socket:
    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM,
    )

    sock.bind(
        (FFB_HOST, FFB_PORT)
    )

    sock.setblocking(False)

    return sock


def receive_latest_force(
    sock: socket.socket,
) -> int | None:
    """Drain queued UDP packets and return only the newest force value."""

    latest = None

    while True:
        try:
            data, _ = sock.recvfrom(64)

        except BlockingIOError:
            break

        if len(data) != 4:
            continue

        latest = struct.unpack(
            "!i",
            data,
        )[0]

    if latest is None:
        return None

    return clamp(
        latest,
        -10000,
        10000,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    signal.signal(
        signal.SIGINT,
        request_stop,
    )

    if hasattr(signal, "SIGTERM"):
        signal.signal(
            signal.SIGTERM,
            request_stop,
        )

    try:
        ffb_socket = create_ffb_socket()

    except OSError as exc:
        print(
            f"Could not bind FFB UDP port "
            f"{FFB_HOST}:{FFB_PORT}: {exc}",
            file=sys.stderr,
        )

        print(
            "Make sure g25_ffb_bridge.py "
            "is not still running.",
            file=sys.stderr,
        )

        return 1

    output = G25Output()

    print(
        "G25Standalone — G25 service"
    )
    print(
        "---------------------------"
    )
    print(
        f"Steering range: "
        f"{args.range_degrees}°"
    )
    print(
        f"FFB bridge: "
        f"{FFB_HOST}:{FFB_PORT}"
    )
    print(
        "Watching for Logitech G25."
    )
    print(
        "Press Ctrl+C to stop."
    )
    print()

    last_state = None
    next_device_poll = 0.0
    retry_after = 0.0

    try:
        while _running:
            now = time.monotonic()

            # ---------------------------------------------------------------
            # High-frequency FFB path
            # ---------------------------------------------------------------

            magnitude = receive_latest_force(
                ffb_socket
            )

            if (
                magnitude is not None
                and output.connected
            ):
                try:
                    output.set_force(
                        magnitude
                    )

                except OSError as exc:
                    print(
                        "[G25] FFB write failed: "
                        f"{exc}",
                        file=sys.stderr,
                    )

                    output.close(
                        send_stop=False
                    )

                    next_device_poll = 0.0

            if output.connected:
                try:
                    output.watchdog()

                except OSError as exc:
                    print(
                        "[G25] FFB watchdog write failed: "
                        f"{exc}",
                        file=sys.stderr,
                    )

                    output.close(
                        send_stop=False
                    )

                    next_device_poll = 0.0

            # ---------------------------------------------------------------
            # Slower USB device watcher
            # ---------------------------------------------------------------

            if now >= next_device_poll:
                next_device_poll = (
                    now
                    + DEVICE_POLL_INTERVAL_SECONDS
                )

                try:
                    detected = detect_g25()

                except Exception as exc:
                    print(
                        "[G25] Detection error: "
                        f"{exc}",
                        file=sys.stderr,
                    )

                    detected = G25Device(
                        WheelState.DISCONNECTED
                    )

                if detected.state != last_state:
                    if detected.state is WheelState.DISCONNECTED:
                        print(
                            "[G25] Disconnected. Waiting..."
                        )

                    elif detected.state is WheelState.LEGACY:
                        print(
                            "[G25] Connected in compatibility "
                            "mode: 046D:C294."
                        )

                    elif detected.state is WheelState.NATIVE:
                        print(
                            "[G25] Connected in native mode: "
                            "046D:C299."
                        )

                    last_state = detected.state

                # -----------------------------------------------------------
                # Disconnected
                # -----------------------------------------------------------

                if detected.state is WheelState.DISCONNECTED:
                    output.close(
                        send_stop=False
                    )

                # -----------------------------------------------------------
                # Legacy C294
                # -----------------------------------------------------------

                elif detected.state is WheelState.LEGACY:
                    output.close(
                        send_stop=False
                    )

                    if now >= retry_after:
                        if switch_to_native_mode(
                            detected.info or {}
                        ):
                            # Force immediate re-detection so we can open
                            # the new C299 device.
                            next_device_poll = 0.0

                        else:
                            retry_after = (
                                time.monotonic()
                                + RETRY_INTERVAL_SECONDS
                            )

                # -----------------------------------------------------------
                # Native C299
                # -----------------------------------------------------------

                elif detected.state is WheelState.NATIVE:
                    info = detected.info or {}

                    current_path = info.get(
                        "path"
                    )

                    needs_open = (
                        not output.connected
                        or output.path != current_path
                    )

                    if (
                        needs_open
                        and now >= retry_after
                    ):
                        try:
                            output.open(
                                info,
                                args.range_degrees,
                            )

                            print(
                                "[G25] Ready."
                            )

                        except OSError as exc:
                            print(
                                "[G25] Could not initialize "
                                f"native output: {exc}",
                                file=sys.stderr,
                            )

                            output.close(
                                send_stop=False
                            )

                            retry_after = (
                                time.monotonic()
                                + RETRY_INTERVAL_SECONDS
                            )

            time.sleep(
                MAIN_LOOP_SLEEP_SECONDS
            )

    except KeyboardInterrupt:
        request_stop()

    finally:
        print()
        print(
            "[G25] Neutralizing force..."
        )

        output.close(
            send_stop=True
        )

        ffb_socket.close()

    print(
        "G25Standalone stopped."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
