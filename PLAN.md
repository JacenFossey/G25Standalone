# G25Standalone Development Plan

## Goal

Plug a Logitech G25 into Windows 11 and use it as a racing controller without Logitech Gaming Software or Logitech Profiler.

The preferred architecture is to reuse Windows' built-in HID support wherever possible and keep Logitech-specific behavior in a small open-source userspace service.

## Phase 0 — Hardware proof

### 0.1 Enumerate and read
- Detect Logitech VID `046D`.
- Detect G25 PID `C294` and/or `C299`.
- List every exposed HID interface.
- Read raw input reports.
- Record which bytes change for:
  - steering
  - throttle
  - brake
  - clutch
  - buttons
  - H-pattern shifter
  - sequential shifter
  - D-pad

**Done when:** we can run our own program on Windows 11, with Logitech Gaming Software absent, and see reliable raw G25 input.

### 0.2 Decode input
- Convert raw reports into named controller state.
- Determine ranges and neutral values.
- Add a live diagnostic display.

**Done when:** the console reports meaningful values such as steering position, three pedals, selected gear, and buttons.

### 0.3 Device control
- Document the Logitech mode-switch command.
- Enter native G25 mode if required.
- Implement steering-range control.
- Test 900-degree mode.

**Done when:** G25Standalone can initialize the wheel and configure steering range without Logitech software.

## Phase 1 — Windows controller path

First test whether Windows already exposes the physical G25 inputs adequately to games.

If yes:
- keep the physical HID input path;
- add only the missing configuration/FFB bridge.

If no:
- add a virtual controller layer;
- prototype with a maintained open-source virtual HID/DirectInput solution;
- replace it later only if necessary.

**Done when:** a game can bind steering, throttle, brake, clutch, shifter, and buttons with Logitech software absent.

## Phase 2 — Force feedback

Implement one effect at a time:

1. constant force;
2. spring;
3. damper;
4. friction;
5. periodic effects;
6. effect lifecycle and gain.

Translate Windows/DirectInput force-feedback requests into the Logitech G25 protocol.

**Done when:** force feedback works correctly in at least one target simulator.

## Phase 3 — Productize

- background Windows service;
- optional control panel;
- configuration persistence;
- device connect/disconnect handling;
- installer;
- modern Windows signing strategy;
- CI builds;
- documentation.

## Non-goals for early versions

- Logitech G Hub compatibility;
- Logitech Profiler profiles;
- GUI before the protocol works;
- supporting every Logitech wheel immediately;
- writing a kernel driver before we prove it is necessary.
