"""Read-only Logitech G25 HID probe for Windows.

This program intentionally sends NO output reports to the device.
It only enumerates matching HID interfaces and attempts to read input reports.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Any

import hid


LOGITECH_VID = 0x046D

KNOWN_G25_PIDS = {
    0xC294: "G25 compatibility / legacy mode",
    0xC299: "G25 native mode",
}

READ_SIZE = 64
READ_TIMEOUT_MS = 100


@dataclass(frozen=True)
class HidInterface:
    path: bytes
    vendor_id: int
    product_id: int
    product_string: str | None
    manufacturer_string: str | None
    serial_number: str | None
    interface_number: int | None
    usage_page: int | None
    usage: int | None

    @classmethod
    def from_hidapi(cls, info: dict[str, Any]) -> "HidInterface":
        return cls(
            path=info["path"],
            vendor_id=info["vendor_id"],
            product_id=info["product_id"],
            product_string=info.get("product_string"),
            manufacturer_string=info.get("manufacturer_string"),
            serial_number=info.get("serial_number"),
            interface_number=info.get("interface_number"),
            usage_page=info.get("usage_page"),
            usage=info.get("usage"),
        )


def hex_id(value: int | None) -> str:
    if value is None:
        return "n/a"
    return f"0x{value:04X}"


def enumerate_logitech_devices() -> list[HidInterface]:
    devices: list[HidInterface] = []

    for raw in hid.enumerate():
        if raw.get("vendor_id") == LOGITECH_VID:
            devices.append(HidInterface.from_hidapi(raw))

    return devices


def print_interface(index: int, device: HidInterface) -> None:
    name = KNOWN_G25_PIDS.get(device.product_id, "other Logitech HID device")

    print(f"[{index}] {name}")
    print(f"    VID:PID       {hex_id(device.vendor_id)}:{hex_id(device.product_id)}")
    print(f"    Product       {device.product_string or '(not reported)'}")
    print(f"    Manufacturer  {device.manufacturer_string or '(not reported)'}")
    print(f"    Serial        {device.serial_number or '(not reported)'}")
    print(f"    Interface     {device.interface_number}")
    print(f"    Usage page    {hex_id(device.usage_page)}")
    print(f"    Usage         {hex_id(device.usage)}")
    print(f"    Path          {device.path!r}")


def g25_interfaces(devices: list[HidInterface]) -> list[HidInterface]:
    return [d for d in devices if d.product_id in KNOWN_G25_PIDS]


def read_interface(device_info: HidInterface) -> None:
    print()
    print("=" * 72)
    print(
        f"Opening PID {hex_id(device_info.product_id)}, "
        f"interface {device_info.interface_number}, "
        f"usage {hex_id(device_info.usage_page)}:{hex_id(device_info.usage)}"
    )
    print("Read-only mode: no output reports will be sent.")
    print("Move the wheel/pedals/shifter/buttons. Press Ctrl+C to stop.")
    print("=" * 72)

    device = hid.device()

    try:
        device.open_path(device_info.path)
        device.set_nonblocking(False)

        last_report: bytes | None = None
        report_count = 0

        while True:
            data = device.read(READ_SIZE, READ_TIMEOUT_MS)

            if not data:
                continue

            report = bytes(data)

            # Avoid filling the console with identical reports.
            if report == last_report:
                continue

            report_count += 1
            last_report = report

            timestamp = time.strftime("%H:%M:%S")
            hex_report = " ".join(f"{byte:02X}" for byte in report)
            print(f"{timestamp}  #{report_count:06d}  {hex_report}")

    finally:
        try:
            device.close()
        except Exception:
            pass


def main() -> int:
    print("G25Standalone — read-only HID probe")
    print("-----------------------------------")

    try:
        devices = enumerate_logitech_devices()
    except Exception as exc:
        print(f"ERROR: HID enumeration failed: {exc}", file=sys.stderr)
        return 1

    if not devices:
        print("No Logitech HID devices were found.")
        print("Check USB connection, power, and Device Manager.")
        return 2

    print(f"Found {len(devices)} Logitech HID interface(s):")
    print()

    for index, device in enumerate(devices):
        print_interface(index, device)
        print()

    candidates = g25_interfaces(devices)

    if not candidates:
        print("No known G25 PID (C294 or C299) was found.")
        print("Do not change drivers yet.")
        print("Copy the enumeration output above so we can inspect what Windows sees.")
        return 3

    print(f"Found {len(candidates)} G25 candidate interface(s).")

    # Try candidate interfaces one at a time. Some HID collections may not allow
    # user-mode input reads; if one fails, continue to the next.
    for candidate in candidates:
        try:
            read_interface(candidate)
        except KeyboardInterrupt:
            print("\nStopped.")
            return 0
        except Exception as exc:
            print()
            print(
                f"Could not read interface {candidate.interface_number} "
                f"(usage {hex_id(candidate.usage_page)}:{hex_id(candidate.usage)}): {exc}"
            )
            print("Trying the next G25 interface, if available.")

    print()
    print("G25 was detected, but no candidate interface produced readable input.")
    print("Copy this program's full output so we can inspect the HID collections.")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
