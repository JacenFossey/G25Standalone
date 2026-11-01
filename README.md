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

## Install and use — standalone Windows app

The standalone installer bundles Python, HID support, and both DirectInput driver architectures. End users need only **64-bit Windows 11 and a Logitech G25**—no Python, build tools, or PowerShell commands.

1. Close games and stop any development copy of `g25_service.py` before installing.
2. Double-click `G25Standalone-0.2.0-Setup.exe` (built below, or obtained from the matching GitHub Actions artifact). The installer is currently **unsigned and experimental**; no public release is published yet.
3. Leave **Start G25Standalone automatically when I sign in** checked.
4. Leave **Start G25Standalone now** checked when setup finishes.
5. Launch a game normally. The app watches for the wheel in the background, even if it was not connected at sign-in.

Start menu → **G25Standalone** provides:

- **Start G25Standalone** — no console window; duplicate launches are ignored.
- **Stop G25Standalone** — requests graceful force neutralization before exiting.
- **Edit steering range settings** — opens `settings.json` in Notepad. Set `range_degrees` to an integer from 40 to 900, save, then use Stop and Start to apply it. Restart games after restarting the controller.
- **Diagnostic logs** — opens `%LOCALAPPDATA%\G25Standalone`. `service.log` (background controller) and `control.log` (install/stop/settings commands) each rotate at 1 MB with three backups. Logging failures cannot prevent force cleanup.
- **Uninstall G25Standalone** — stops the runtime and restores the pre-first-install registry backup before removing program files.

Installation is per-user and does not require administrator rights. Startup happens **at sign-in**, not before a user logs in. Upgrades retain the original registry backup. Settings, logs, and the original recovery backup remain after uninstall. Close games before upgrading or uninstalling; game processes may still hold the driver DLLs open.

There is no tray icon/control panel yet. Windows Task Manager → Startup apps can disable automatic startup. Do not run the installed app and a development service at the same time.

Do not install a WinUSB/libusb filter driver or use Zadig. G25Standalone relies on the standard Windows HID stack.

## Build the standalone installer — developers

Requirements: Python 3 (64-bit), Visual Studio C++ tools and Windows SDK, CMake 3.24+, and Inno Setup 6. PyInstaller is pinned in `requirements-build.txt`.

```powershell
python -m pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File .\scripts\Build-Standalone.ps1
```

Outputs:

- `dist\G25Standalone\` — self-contained folder bundle; keep all files together.
- `dist\installer\G25Standalone-0.2.0-Setup.exe` — per-user installer.

`-SkipInstaller` builds/checks the folder bundle without Inno Setup. `-Python`, `-CMake`, `-ISCC`, and `-Version` override build inputs. The smoke check imports bundled HID support and verifies both driver architectures **without opening the wheel or modifying registration**.

GitHub Actions also produces unsigned installer and folder-bundle artifacts. Creating/publishing a release and signing the installer are separate steps, gated on hardware validation.

## Set up the service — source/development

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

GitHub Actions builds both registered DLL architectures, runs Python and mocked PowerShell registration tests, and builds/smoke-checks the standalone installer. The lifecycle integration tests use isolated named Windows objects and synthetic processes, not the physical wheel.

For the mocked registry transaction tests:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\test_registration.ps1
```

Before release, test the installer on a clean Windows user account: install, check sign-in startup, exercise Start/Stop, upgrade, and uninstall; verify that the original registry state is restored. Then follow the hardware checklist in `PLAN.md`.

## Safety and limitations

- This is still experimental driver-adjacent software; validate each game before relying on it.
- The service sends neutral/stop commands during normal shutdown and keeps physical wheel ownership out of game processes.
- The 12 effects are implemented, but their exact physical feel still needs game-by-game tuning, especially inertia/friction derivative scaling.
- The application-local proxy is intentionally retained because some older games may depend on DirectInput behavior that a registered OEM effect driver cannot perfectly reproduce.
- Do not send arbitrary HID reports to the wheel.
- Restart games after restarting the app: reconnect/state replay for already-open games is not implemented yet.
- Stop requests neutralization before exit; the hidden Windows session-notification window also requests it during normal sign-out/shutdown. Session-end cleanup is best-effort and needs hardware validation. Forcibly terminating the app or losing power does not guarantee a final HID stop command. Avoid killing the controller while torque is active.

See [PLAN.md](PLAN.md) for the development roadmap and validation checklist.
