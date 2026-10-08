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

The original local proxy has already been exercised successfully in Richard Burns Rally and Colin McRae Rally 2.0. On October 8, 2026, the project owner confirmed gameplay validation of the registered-driver branch in Live for Speed, iRacing, and Richard Burns Rally. Targeted lifecycle checks and installer validation remain outstanding; this is not yet an installer-ready release.

Final force output uses the latest low-pass smoothing before conversion to the G25's 8-bit command, rather than the earlier stair-step hysteresis. Safety/lifecycle neutralization bypasses smoothing and returns to zero immediately.

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
- Logitech G25

The Windows bundle includes Python/HID dependencies and both registered-driver
architectures. Download `G25Standalone-windows-x64` from a successful
[Windows bundle Actions run](../../actions/workflows/windows-bundle.yml), extract
the artifact and then the versioned ZIP inside it, and follow its `QUICKSTART.md`.
Keep the entire extracted folder in a stable location before registering its
drivers. CI exercises the executable; fresh Windows 11 and physical-wheel
acceptance remain outstanding. This is a portable preview, not an installer.

For development from source, install Python 3, Visual Studio Build Tools 2022
with the C++ workload and Windows SDK, and CMake 3.24+.

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

With no saved setting, steering range defaults to 900 degrees. For a temporary override:

```powershell
py .\src\g25_service.py --range 540
```

## Background runtime and settings

The runtime can now be managed without keeping a console open:

```powershell
py .\src\g25_service.py settings --range 540
py .\src\g25_service.py start
py .\src\g25_service.py status
py .\src\g25_service.py stop
```

| Command | Behavior |
| --- | --- |
| No command, or `run` | Run in the foreground; Ctrl+C requests a clean stop. |
| `start` | Launch a background process with no console and return its status. Repeating this command returns the existing process's status. |
| `status` | Report process state, wheel state, active steering range, PID, and log path. A running process can be waiting for a wheel; `ready` means the output device was initialized. |
| `stop` | Request cooperative shutdown and wait for hardware cleanup and release of the instance lock. An unresponsive process is not force-killed. |
| `settings` | Show the saved settings and their location. |
| `settings --range 540` | Save a range from 40–900 degrees for the next start. This does not change an active session. |

`run --range 540` and `start --range 540` override the saved range for that session only. To apply a saved change, close the game, run `stop`, then `start`, and reopen the game. Restarting the background process while a game remains open does not yet replay its downloaded force effects.

Settings are stored in `%LOCALAPPDATA%\G25Standalone\settings.json`. Runtime logs are stored in `%LOCALAPPDATA%\G25Standalone\logs\g25.log`, with three rotated backups and a 1 MiB rotation threshold. Existing driver-registration backups in the same application data directory are preserved. Corrupt or unsupported settings cause a startup error instead of being overwritten; correct the settings file before starting again.

Only one managed process can use a data directory. Exit codes are `0` for successful commands, `1` for errors, `2` for an attempted duplicate `run`, and `3` when `status` finds no responding runtime. `stop` succeeds if no process owns the runtime lock; a stale status file does not authorize terminating a PID. Startup/stop waits are bounded, and failures point to diagnostics rather than silently claiming success.

Windows sign-out/shutdown notifications request the same cooperative cleanup as `stop`. Forced process termination, power loss, and device failure cannot guarantee a final HID write; use the management command for routine stopping. The automated shutdown tests use mocked HID output, so physical-wheel sign-out behavior remains an acceptance check.

The bundled executable accepts the same commands: replace
`py .\src\g25_service.py` with `.\G25Standalone.exe`. It includes its own runtime;
Python is required only for source development. Automatic sign-in startup is
not installed yet; the per-user installer is the next development step.
`--data-dir PATH` is available for isolated development/tests; normal use should
keep the default so all commands address the same instance.

## Build the Windows bundle

Install the x64 CPython version in `packaging/python-version.txt`, Visual Studio
Build Tools 2022 (C++/Windows SDK), and CMake 3.24+, then run from PowerShell:

```powershell
.\scripts\Build-WindowsBundle.ps1 -Python python
```

The script creates a fresh build environment, installs the complete wheel-only
dependency lock with SHA-256 verification, builds both driver architectures,
and uses the checked-in PyInstaller specification. The drivers statically link
the MSVC runtime; required runtime DLLs for Python/HID are bundled. Native
imports and architecture are checked before ZIP assembly. Do not copy just the
executable out of the bundle: it needs the adjacent `_internal` folder.

`dist` receives a versioned ZIP and its checksum. `BUILD-INFO.json` inside the
ZIP records the source revision, package versions, native imports and file
hashes. On a Windows build host without an attached G25, test the shipping ZIP:

```powershell
python .\packaging\smoke_bundle.py (Get-ChildItem .\dist\*.zip).FullName
```

The test extracts to a path containing spaces, changes working directory and
removes Python/tool paths from the executable's environment. It exercises real
HID loading, settings, independent background startup, status, duplicate
protection and cooperative stop. It does not register drivers or change the
normal user's settings. CI uses a Windows Server build host; a clean Windows 11
machine without development tools/VC redistributables and gameplay in LFS,
iRacing and RBR remain the release acceptance checks. This preview does not
include the separately built legacy proxy or add installer/startup behavior.

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

The proxy mixes simultaneous constant-force effects, applies effect/device gain and Cartesian direction, and sends a 25 ms heartbeat to keep sustained effects alive under the service's 150 ms watchdog. Rebuild and replace existing game-folder DLLs to use these changes. The fallback still supports constant force only and does not implement the registered path's full duration/envelope/reset semantics.

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

GitHub Actions builds the registered DLL for both Win32 and x64, runs the Python
tests, and builds/tests the downloadable Windows ZIP.

The Python suite also checks signed force smoothing, small sustained forces, and immediate neutralization using mocked HID output. The separate Native proxy workflow builds and tests the x86 fallback; locally, run `native\dinput8\test.bat` from that directory in an x86 Native Tools prompt.

## Safety and limitations

- This is still experimental driver-adjacent software; validate each game before relying on it.
- The service sends neutral/stop commands during normal shutdown and keeps physical wheel ownership out of game processes.
- The 12 effects are implemented, but their exact physical feel still needs game-by-game tuning, especially inertia/friction derivative scaling.
- The application-local proxy is intentionally retained because some older games may depend on DirectInput behavior that a registered OEM effect driver cannot perfectly reproduce.
- Do not send arbitrary HID reports to the wheel.

See [PLAN.md](PLAN.md) for the development roadmap and validation checklist.
