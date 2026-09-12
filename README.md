# G25Standalone

An experimental, open-source Windows 11 controller stack for the Logitech G25 racing wheel.

## Current milestone

**0.1 — Read the wheel without Logitech Gaming Software**

The first probe is intentionally read-only. It:

- finds Logitech HID devices;
- identifies known G25 compatibility/native-mode product IDs;
- prints HID interface details;
- attempts to open each G25 HID interface;
- streams raw input reports as hexadecimal.

It does **not** send initialization, steering-range, or force-feedback commands yet.

## Hardware IDs

Known Logitech G25 IDs used by this project:

- Vendor ID: `046D`
- Product ID `C294`: compatibility/legacy mode
- Product ID `C299`: native G25 mode

## Windows setup

Create and activate a Python virtual environment:

```powershell
cd C:\dev\G25Standalone
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
pip install -r requirements.txt
```

Then connect the G25 and run:

```powershell
py .\src\g25_probe.py
```

Turn the wheel, press each pedal, move the shifter, and press buttons. The program should print changing HID reports.

Press `Ctrl+C` to stop.

## Important

For now, do **not** install a WinUSB/libusb filter driver for the G25 and do not use Zadig. This probe is designed to use the standard Windows HID stack.

Do not send arbitrary HID output reports to the wheel. Output support will be added only after we document the required Logitech commands.

## Project direction

See [PLAN.md](PLAN.md).
