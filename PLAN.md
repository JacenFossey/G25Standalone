# G25Standalone Development Plan

## Goal

Use a Logitech G25 as a complete racing controller on Windows 11 without Logitech Gaming Software or Logitech Profiler.

The architecture keeps ordinary controller input on Windows' built-in HID/DirectInput path. Logitech-specific initialization, steering range, and force output live in a small userspace service, while an application-local DirectInput proxy exposes missing FFB capability to games.

## Current baseline

The proof of concept is working end to end:

- the service detects both G25 product modes and switches to native mode;
- Windows supplies steering, pedals, shifter, and buttons directly to games;
- the service configures steering range and disables the default centering spring;
- a 32-bit `dinput8.dll` proxy advertises constant-force support;
- the proxy forwards game force samples to the service over localhost UDP;
- the service translates those samples into Logitech HID force reports;
- a watchdog neutralizes force when samples stop;
- force feedback works in Richard Burns Rally and Colin McRae Rally 2.0.

## Phase 0 — Hardware proof: complete

- [x] Detect Logitech VID `046D` and G25 PIDs `C294`/`C299`.
- [x] Enumerate and read the wheel through the standard HID stack.
- [x] Decode steering, pedals, shifter, D-pad, and buttons.
- [x] Switch compatibility mode to native G25 mode.
- [x] Configure and test steering range up to 900 degrees.

## Phase 1 — Windows controller path: complete

- [x] Verify that Windows exposes normal G25 inputs adequately to games.
- [x] Keep the physical HID input path rather than introducing a virtual controller.
- [x] Limit the custom layer to wheel configuration and force feedback.

## Phase 2 — Force feedback: in progress

- [x] Prove constant-force output directly against the G25 protocol.
- [x] Advertise a synthetic FFB driver and steering actuator through DirectInput.
- [x] Implement DirectInput constant-force creation, update, start, stop, and unload.
- [x] Bridge force samples from the proxy to the service over localhost UDP.
- [x] Disable the default centering spring while game FFB is active.
- [x] Add a loss-of-signal watchdog and shutdown neutralization.
- [x] Validate the path in at least two 32-bit games.
- [ ] Apply DirectInput device/effect gain consistently to outgoing force.
- [ ] Confirm direction handling and sign across more games.
- [ ] Implement spring, damper, friction, and periodic effects as real games require them.
- [ ] Define clean behavior for multiple simultaneous effects.
- [ ] Add a separate x64 proxy build for 64-bit games.

**Done when:** the supported effect set behaves predictably across a representative group of 32-bit and 64-bit games, with safe lifecycle handling.

## Phase 3 — Reliability and usability

- [ ] Turn the Python service into a background Windows application/service.
- [ ] Add automatic startup and reliable device connect/disconnect handling.
- [ ] Persist steering range and other configuration.
- [ ] Replace development logging with configurable, bounded diagnostics.
- [ ] Add automated tests for force conversion, watchdog behavior, and protocol reports.
- [ ] Add reproducible x86/x64 CI builds.
- [ ] Package the service and both proxy architectures in an installer.
- [ ] Establish a Windows signing and release strategy.
- [ ] Add a small control panel only after the runtime is stable.

## Immediate next steps

1. Verify gain and direction behavior with targeted tests.
2. Capture unsupported effect requests from additional games.
3. Implement the next effect type based on real compatibility needs.
4. Produce an x64 proxy alongside the guarded x86 build.
5. Design the smallest reliable startup/install flow.

## Non-goals for early versions

- Logitech G Hub compatibility.
- Logitech Profiler profile emulation.
- Supporting every Logitech wheel immediately.
- A custom kernel driver before the userspace approach proves insufficient.
- A polished GUI before runtime reliability and compatibility are established.
