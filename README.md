# G25Standalone

An experimental, open-source Windows 11 controller stack for the Logitech G25 racing wheel. It runs the wheel without Logitech Gaming Software or Logitech Profiler.

## Current status

The working prototype now:

- detects the G25 in compatibility mode (`046D:C294`) or native mode (`046D:C299`);
- switches the wheel into native mode;
- configures up to 900 degrees of steering range;
- leaves normal wheel, pedal, shifter, and button input on Windows' built-in HID/DirectInput path;
- exposes DirectInput constant-force feedback to 32-bit games through a local `dinput8.dll` proxy;
- forwards force samples over localhost UDP to the G25 service;
- disables the wheel's default centering spring while game FFB is active;
- returns the wheel to neutral if the game or proxy stops sending force.

Constant-force feedback has been exercised successfully in Richard Burns Rally and Colin McRae Rally 2.0. This is still a development prototype, not an installer-ready driver replacement.

## Requirements

- Windows 11
- Python 3
- Microsoft Visual Studio Build Tools with the C++ workload
- a Logitech G25

Do not install a WinUSB/libusb filter driver or use Zadig. G25Standalone relies on the standard Windows HID stack.

## Set up the service

Create and activate a Python virtual environment:

```powershell
cd C:\Dev\G25Standalone
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
pip install -r requirements.txt
```

Connect the wheel, then start the service:

```powershell
py .\src\g25_service.py
```

The default steering range is 900 degrees. To choose another range:

```powershell
py .\src\g25_service.py --range 540
```

Leave the service running while playing. Press `Ctrl+C` to stop it safely.

## Build and install the DirectInput proxy

The currently supported target is a **32-bit game**, so the proxy must also be 32-bit.

1. Open an **x86 Native Tools Command Prompt for Visual Studio**.
2. Build the proxy:

   ```bat
   cd C:\Dev\G25Standalone\native\dinput8
   build.bat
   ```

3. Copy `native\dinput8\build\dinput8.dll` beside the game's executable—the executable that actually starts the game, not necessarily its launcher.
4. Start `g25_service.py`, then launch the game.

The proxy writes `g25_dinput8.log` beside the game executable for diagnostics. Build output and runtime logs are intentionally not tracked by Git.

A 32-bit proxy cannot be loaded by a 64-bit game. Supporting 64-bit games will require a separate x64 build of the proxy.

## Architecture

Normal controller input continues to flow directly from the G25 through Windows. Only missing wheel configuration and force feedback are handled by this project:

```text
32-bit game -> local dinput8.dll proxy -> UDP 127.0.0.1:26725
             -> g25_service.py -> Logitech HID force reports -> G25
```

## Safety and limitations

- Only DirectInput constant-force effects are implemented.
- The proxy is an application-local compatibility layer, not a kernel driver.
- The service includes a short FFB watchdog and sends neutral/stop commands during shutdown.
- Do not send arbitrary HID output reports to the wheel.

See [PLAN.md](PLAN.md) for completed milestones and next steps.
