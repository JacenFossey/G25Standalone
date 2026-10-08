# G25Standalone Windows preview

For 64-bit Windows 11 and the Logitech G25. This ZIP includes the Python/HID
runtime and both 32-bit and 64-bit registered DirectInput drivers. Python,
build tools, and a separate Visual C++ runtime installation are not required
to run it. This is a portable preview; installer and sign-in startup come next.

## Extract and register

Extract the **whole** ZIP to a stable location, for example
`C:\Users\YourName\Apps\G25Standalone`. Keep `G25Standalone.exe` beside its
`_internal` folder. Open PowerShell in that extracted folder.

Close your racing games and stop any existing G25Standalone runtime first.
If you previously registered a source build, use its registration script with
`-Action Uninstall` before registering this bundle. Existing registration
backups cause a second installation to be refused.

```powershell
powershell -ExecutionPolicy Bypass -File .\Register-G25StandaloneFF.ps1 `
  -Action Install `
  -Dll32 .\drivers\x86\g25ff.dll `
  -Dll64 .\drivers\x64\g25ff.dll
```

Registration is per user. Leave the folder in this location once registered:
Windows stores the absolute DLL paths. Do not replace your system `dinput8.dll`
or install a WinUSB/libusb filter driver. Normal input uses Windows HID.

## Run

```powershell
.\G25Standalone.exe settings --range 540
.\G25Standalone.exe start
.\G25Standalone.exe status
```

`start` launches a hidden background process and returns. Repeating it returns
the existing process. `waiting` / `disconnected` means it is running but has not
found a wheel. Connect the G25; wait for `ready`, then launch your game normally.
Omit `settings --range 540` for the default 900 degrees. Supported range: 40–900.

```powershell
.\G25Standalone.exe stop
```

`stop` waits for cooperative cleanup. `run` starts in the foreground for
diagnostics; Ctrl+C requests cleanup. A temporary `start --range 450` changes
only that session. Saved settings apply at the next start. Close the game before
restarting the runtime; reopening the game recreates its downloaded effects.

Settings: `%LOCALAPPDATA%\G25Standalone\settings.json`.
Rotating logs: `%LOCALAPPDATA%\G25Standalone\logs\g25.log`.
Driver registration backups remain in this same per-user directory. The app
does not automatically start at sign-in yet. Run it again after signing in.

## Remove or replace the bundle

Close the games, run `stop`, then restore the prior registration **before**
deleting, moving, or replacing the folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\Register-G25StandaloneFF.ps1 -Action Uninstall
```

Then delete the extracted folder. Settings, logs, and registration backups are
retained. For an upgrade, extract the new bundle to its final location and
register its two DLLs again. Automatic upgrade/rollback belongs to the upcoming
installer.

## Acceptance checks

CI tests the extracted executable, including native HID loading, settings,
detached startup, duplicate protection, status and cleanup. Before calling this
an installable release, validate on a fresh Windows 11 machine without Python,
build tools or Visual C++ redistributables, then on the physical G25:

1. Start, reach `ready`, and run LFS, iRacing and RBR with the registered drivers.
2. Compare force feel with the validated source runtime; smoothing is unchanged.
3. Stop during active force; verify neutral output. Check unplug/replug recovery.
4. Confirm Windows sign-out/shutdown neutralizes the wheel.
5. Restore registration, replace the bundle, register again and repeat a game run.

`BUILD-INFO.json` records the source revision, dependency versions, native DLL
imports and file hashes. The adjacent ZIP checksum detects download corruption.
The preview is unsigned; signing and the installer are separate milestones.
