# G25Standalone Development Plan

## Goal

Use a Logitech G25 as a complete racing controller on Windows 11 without Logitech Gaming Software or Logitech Profiler.

Normal steering/pedal/shifter/button input stays on Windows' built-in HID/DirectInput path. A background userspace service owns all Logitech-specific hardware I/O. The preferred game integration is now a registered DirectInput OEM force-feedback driver, installed once for both 32-bit and 64-bit games. The original local `dinput8.dll` proxy remains as a compatibility fallback for games such as old rally titles that prove unreliable through the OEM driver path.

## Current baseline

The original proof of concept is known-good in Richard Burns Rally and Colin McRae Rally 2.0:

- service detects C294/C299 and switches to native mode;
- service configures steering range and owns the G25 HID output handle;
- Windows supplies ordinary input directly to games;
- local 32-bit `dinput8.dll` proxy exposes constant-force FFB and forwards it to the service;
- watchdog/shutdown paths neutralize force.

The current branch extends that architecture with:

- a registered x86/x64 DirectInput `IDirectInputEffectDriver` COM DLL;
- per-user G25 OEM/FFB registration with reversible registry backup;
- localhost TCP IPC from game-side driver to service;
- a service-side 12-effect renderer;
- live wheel kinematics for condition effects;
- automated effect tests and Windows x86/x64 CI builds;
- retained local proxy path for per-game compatibility fallback.

## Phase 0 — Hardware proof: complete

- [x] Detect Logitech VID `046D` and G25 PIDs `C294`/`C299`.
- [x] Enumerate and read the wheel through the standard HID stack.
- [x] Decode steering, pedals, shifter, D-pad, and buttons.
- [x] Switch compatibility mode to native G25 mode.
- [x] Configure and test steering range up to 900 degrees.

## Phase 1 — Windows controller path: complete

- [x] Verify Windows exposes ordinary G25 inputs adequately.
- [x] Keep the physical HID input path rather than introducing a virtual controller.
- [x] Keep custom code focused on G25 initialization/range/FFB.

## Phase 2 — Install-once DirectInput driver: implementation complete, validation in progress

- [x] Register an OEM force-feedback COM driver for `VID_046D&PID_C299`.
- [x] Build separate Win32 and x64 DLLs.
- [x] Implement `IDirectInputEffectDriver` lifecycle methods.
- [x] Keep the game-side driver hardware-free; forward state to the service only.
- [x] Preserve the original local `dinput8.dll` compatibility path.
- [x] Add reversible per-user registry install/uninstall.
- [ ] Confirm the registered path enumerates cleanly in `joy.cpl` / DirectInput probes.
- [ ] Validate RBR startup/re-detect/restart behavior against the local-proxy baseline.
- [ ] Validate LFS repeatedly without a local proxy DLL.
- [ ] Validate at least one additional 32-bit game and one 64-bit game.

## Phase 3 — Full DirectInput effect set: implementation complete, tuning in progress

Implemented effect classes:

- [x] Constant Force
- [x] Ramp Force
- [x] Square
- [x] Sine
- [x] Triangle
- [x] Sawtooth Up
- [x] Sawtooth Down
- [x] Spring
- [x] Damper
- [x] Inertia
- [x] Friction
- [x] Custom Force

Effect semantics:

- [x] Per-effect gain.
- [x] Device gain.
- [x] Direction/sign.
- [x] Duration and iterations.
- [x] Start delay.
- [x] Attack/fade envelopes.
- [x] Multiple simultaneous effects mixed and clamped safely.
- [x] `STOPALL`, pause/continue, actuator on/off, and reset behavior.
- [x] Reset restores actuators (important for games that disable then reset FFB).
- [x] Spring based on live wheel position.
- [x] Damper based on wheel velocity.
- [x] Inertia based on wheel acceleration.
- [x] Friction based on wheel movement direction.
- [x] Unit tests covering all 12 effect classes.
- [ ] Tune derivative filtering/scaling on real G25 hardware.
- [ ] Compare physical feel against known-good Logitech/LFS behavior.
- [ ] Capture game-specific effect traffic for RBR/LFS and correct edge cases.

## Phase 4 — Reliability and packaging

- [x] Bundle the Python service/HID runtime as a windowless Windows background process.
- [x] Add per-user installer, default sign-in startup, and Start/Stop shortcuts.
- [x] Add single-instance ownership and graceful stop before upgrade/uninstall.
- [x] Persist steering range in per-user settings with validation.
- [x] Add bounded diagnostic logging for driver IPC and effect lifecycle.
- [x] Preserve pre-first-install registry backups across upgrades with rollback on registration errors.
- [x] Add hardware-free IPC, output safety, Windows lifecycle, and mocked registry transaction tests.
- [ ] Validate install/sign-in/upgrade/uninstall on a clean Windows account, including sign-out during active force.
- [ ] Add service reconnect/state-replay if the service restarts while a game is still open.
- [x] Add reproducible x86/x64 driver CI builds.
- [x] Define CI artifacts containing bundled runtime + x86/x64 DLLs + unsigned installer.
- [ ] Publish a release after installer and physical-wheel validation.
- [ ] Establish signing/release strategy (initial test artifacts are unsigned).
- [ ] Add a small tray/control UI after runtime behavior is stable.

## Standalone installer validation checklist

1. Build the folder bundle and installer; package smoke check must pass without hardware/registry I/O.
2. On a clean Windows user account, install without elevation and leave sign-in startup enabled.
3. Verify bundled runtime runs without installed Python/build tools or a console window.
4. Launch Start twice; confirm only one controller owns the wheel.
5. Use Stop during low force; verify immediate neutralization and process exit.
6. Edit steering range settings, Stop/Start, and confirm the persisted range.
7. Sign out/in and confirm automatic startup; check the log after startup failures.
8. Upgrade with games closed; confirm original registry backups and settings are retained.
9. Uninstall; confirm startup entry/shortcuts/program files are removed and pre-first-install registry state restored.
10. Exercise error paths (missing backup, failed registration, stop timeout); do not delete program files when safe cleanup cannot be completed.

## Hardware validation checklist

1. Build/register x86 and x64 `g25ff.dll`.
2. Start `g25_service.py` with no local `dinput8.dll` present.
3. Confirm G25 reaches C299 and service reports Ready.
4. Run a DirectInput inventory and verify FFB + 12 effects are advertised.
5. Launch LFS repeatedly; verify input and FFB every launch.
6. Launch RBR repeatedly; record whether input and FFB work before any Redetect Devices action.
7. Compare RBR against the local-proxy fallback on the same machine/session.
8. Exercise constant, periodic, spring, damper, inertia, and friction effects on hardware.
9. Unplug/replug between runs and verify service recovery.
10. Kill a game during active force and verify prompt neutralization.

## Non-goals for early versions

- Logitech G Hub/Profiler UI emulation.
- Supporting every Logitech wheel immediately.
- A custom kernel driver unless the userspace DirectInput approach proves insufficient.
- Removing the local compatibility proxy simply for architectural purity.
- A polished control panel before compatibility and safety are validated.
