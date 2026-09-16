# G25Standalone

An experimental, open-source Windows 11 controller stack for the Logitech G25 racing wheel. It runs the wheel without Logitech Gaming Software or Logitech Profiler.

## Current status

G25Standalone now has two force-feedback paths:

1. **Registered DirectInput driver (preferred):** install once and ordinary 32-bit or 64-bit DirectInput games can use the G25 without a DLL in each game folder.
2. **Local `dinput8.dll` compatibility proxy:** the original proven path for old or unusual games that do not behave correctly with the registered OEM effect driver.

The service remains the single owner of the physical wheel. It:

- detects `046D:C294` / `046D:C299` and switches the G25 into native mode;
- configures steering range up to 900 degrees;
- leaves normal steering, pedals, shifter, POV, and buttons on Windows' built-in HID/DirectInput input path;
- receives DirectInput effect state from the registered driver over localhost TCP;
- renders all 12 standard DirectInput effect classes;
- translates the resulting force into Logitech lg4ff HID output;
- retains the original local-proxy UDP path as a fallback;
- neutralizes force on shutdown, disconnect, or loss of the legacy proxy.

The original local proxy has already been exercised successfully in Richard Burns Rally and Colin McRae Rally 2.0. The new registered-driver path is under active hardware validation.

## Supported DirectInput effects

The registered driver advertises and implements:

- Constant Force
- Ramp Force
- Square
- Sine
- Triangle
- Sawtooth Up
- Sawtooth Down
- Spring
- Damper
- Inertia
- Friction
- Custom Force

Constant/ramp/periodic/custom effects are synthesized in the service. Spring, damper, inertia, and friction use live wheel position/velocity/acceleration read from the G25 native HID report.

## Requirements

- Windows 11, 64-bit
- Python 3
- Microsoft Visual Studio Build Tools 2022 with the C++ workload and Windows SDK
- CMake 3.24+
- Logitech G25

Do not install a WinUSB/libusb filter driver or use Zadig. G25Standalone relies on the standard Windows HID stack.

## Set up the service

```powershell
cd C:\Dev\G25Standalone
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
pip install -r requirements.txt
py .\src\g25_service.py
```

The default steering range is 900 degrees. For another range:

```powershell
py .\src\g25_service.py --range 540
```

## Build the install-once DirectInput driver

Build both architectures because many older racing games (including RBR) are 32-bit while newer games may be 64-bit.

```powershell
cmake -S native/g25ff -B build/g25ff-x86 -A Win32
cmake --build build/g25ff-x86 --config Release

cmake -S native/g25ff -B build/g25ff-x64 -A x64
cmake --build build/g25ff-x64 --config Release
```

The resulting DLLs are:

```text
build\g25ff-x86\Release\g25ff.dll
build\g25ff-x64\Release\g25ff.dll
```

Register them for the current Windows user:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Register-G25StandaloneFF.ps1 `
  -Action Install `
  -Dll32 .\build\g25ff-x86\Release\g25ff.dll `
  -Dll64 .\build\g25ff-x64\Release\g25ff.dll
```

Then start `g25_service.py` and launch a game normally. No game-folder DLL should be necessary.

To remove the registration and restore whatever registry state existed before installation:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Register-G25StandaloneFF.ps1 -Action Uninstall
```

## Legacy compatibility proxy

If a game is unreliable with the registered driver, the original application-local proxy remains available.

Open an **x86 Native Tools Command Prompt for Visual Studio**, run:

```bat
cd C:\Dev\G25Standalone\native\dinput8
build.bat
```

Copy `native\dinput8\build\dinput8.dll` beside the 32-bit game's real executable and run the normal G25 service. The proxy forwards constant-force samples over UDP `127.0.0.1:26725`.

When a registered-driver client is active, the service gives it priority over legacy proxy packets.

## Architecture

```text
Preferred / install-once path

Game
  -> Windows dinput8.dll / DirectInput
  -> registered G25Standalone g25ff.dll (x86 or x64)
  -> TCP 127.0.0.1:26726
  -> G25 service / 12-effect renderer
  -> Logitech HID
  -> G25

Compatibility path

Old/problematic game
  -> local dinput8.dll proxy
  -> UDP 127.0.0.1:26725
  -> G25 service
  -> Logitech HID
  -> G25
```

The game-side registered DLL never opens the physical wheel. Device ownership, safety neutralization, reconnect handling, steering range, and all HID writes remain centralized in the service.

## Validation

Run the effect-engine tests with:

```powershell
python -m unittest discover -s tests -v
```

GitHub Actions builds the registered DLL for both Win32 and x64 and runs the Python effect tests.

## Safety and limitations

- This is still experimental driver-adjacent software; validate each game before relying on it.
- The service sends neutral/stop commands during normal shutdown and keeps physical wheel ownership out of game processes.
- The 12 effects are implemented, but their exact physical feel still needs game-by-game tuning, especially inertia/friction derivative scaling.
- The application-local proxy is intentionally retained because some older games may depend on DirectInput behavior that a registered OEM effect driver cannot perfectly reproduce.
- Do not send arbitrary HID reports to the wheel.

See [PLAN.md](PLAN.md) for the development roadmap and validation checklist.
