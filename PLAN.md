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

On October 8, 2026, the project owner confirmed gameplay validation of the registered-driver branch in Live for Speed, iRacing, and Richard Burns Rally. This establishes game-use validation; the targeted startup/restart/disconnect checks below remain separate acceptance work.

The integrated fallback proxy now includes simultaneous constant-force mixing, device/effect gain, Cartesian direction handling, a 25 ms heartbeat, and its x86 build/test workflow. The registered service retains the latest final-output low-pass smoothing from commit `295b122`, with immediate safety/lifecycle neutralization. The fallback's new behavior still needs targeted physical-wheel checks; it remains constant-force-only with incomplete duration/envelope/reset semantics.

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

## Phase 2 — Install-once DirectInput driver: implementation and gameplay validation complete, lifecycle checks remain

- [x] Register an OEM force-feedback COM driver for `VID_046D&PID_C299`.
- [x] Build separate Win32 and x64 DLLs.
- [x] Implement `IDirectInputEffectDriver` lifecycle methods.
- [x] Keep the game-side driver hardware-free; forward state to the service only.
- [x] Preserve the original local `dinput8.dll` compatibility path.
- [x] Add reversible per-user registry install/uninstall.
- [x] Confirm gameplay in LFS, iRacing, and RBR (owner report, October 8, 2026).
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
- [x] Preserve final-output smoothing and add hardware-free regression tests for signed steps, small sustained force, and immediate neutralization.
- [ ] Tune derivative filtering/scaling on real G25 hardware.
- [ ] Compare physical feel against known-good Logitech/LFS behavior.
- [ ] Capture game-specific effect traffic for RBR/LFS and correct edge cases.

## Phase 4 — Reliability and packaging

- [x] Package the runtime into a standalone Windows x64 executable bundle with both driver architectures and CI smoke checks.
- [ ] Accept the bundle on clean Windows 11 without Python, build tools or VC redistributables.
- [ ] Start automatically at sign-in/boot with clean shutdown behavior.
- [x] Persist steering range with validated, atomic per-user settings; session overrides do not overwrite it.
- [x] Add rotating runtime/HID lifecycle logs and foreground/background logging modes.
- [ ] Extend bounded diagnostics to driver IPC and effect lifecycle.
- [x] Add single-instance protection and status/start/stop management commands.
- [x] Request cooperative neutralization on stop, signals, and confirmed Windows session end.
- [ ] Confirm background stop and Windows sign-out/shutdown on the physical G25 (automated coverage uses mocked HID).
- [ ] Add service reconnect/state-replay if the service restarts while a game is still open.
- [ ] Harden registry backup/restore error handling and partial-install rollback before installer release.
- [x] Add reproducible x86/x64 driver CI builds.
- [ ] Add release artifacts containing service + x86/x64 DLLs + installer.
- [ ] Establish signing/release strategy.
- [ ] Add a small tray/control UI after runtime behavior is stable.

## Next development milestone — Minimal Windows installer

Package the service and HID runtime into an executable, start it at Windows sign-in, persist steering range, and install both registered-driver DLLs in stable locations. Include upgrade/uninstall behavior that restores prior registration. Validate a fresh install, reboot, unplug/replug, service restart, upgrade, and uninstall on Windows without Python or development tools. Keep the established registered-driver force rendering and smoothing as the gameplay baseline.

Implementation sequence:

1. Background runtime management: persistent range, rotating logs, single instance, process commands, and cooperative shutdown. Merged; acceptance testing on physical hardware remains.
2. Packaged executable: bundle Python/HID dependencies and both drivers, pin/hash-check build packages, and exercise the extracted ZIP in CI. Implemented; clean Windows 11 and physical-wheel acceptance remain.
3. Per-user installer: driver registration, optional sign-in startup, clean upgrades/uninstall, and registry backup/rollback hardening.
4. Release pipeline and installed-game acceptance in LFS, iRacing, and RBR.

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
