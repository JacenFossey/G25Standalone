#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif

[Setup]
AppId={{F1571E1D-B59D-4322-BAC1-EBD860FA40D7}
AppName=G25Standalone
AppVersion={#AppVersion}
AppPublisher=G25Standalone contributors
AppPublisherURL=https://github.com/JacenFossey/G25Standalone
DefaultDirName={localappdata}\Programs\G25Standalone
DefaultGroupName=G25Standalone
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
MinVersion=10.0.22000
OutputDir=..\dist\installer
OutputBaseFilename=G25Standalone-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\G25Standalone.exe
SetupLogging=yes

[Tasks]
Name: "autostart"; Description: "Start G25Standalone automatically when I sign in"; Flags: checkedonce

[Files]
Source: "..\dist\G25Standalone\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Start G25Standalone"; Filename: "{app}\G25Standalone.exe"
Name: "{group}\Stop G25Standalone"; Filename: "{app}\G25Standalone.exe"; Parameters: "--stop"
Name: "{group}\Edit steering range settings"; Filename: "{app}\G25Standalone.exe"; Parameters: "--settings"
Name: "{group}\Diagnostic logs"; Filename: "{localappdata}\G25Standalone"
Name: "{group}\Uninstall G25Standalone"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "G25Standalone"; ValueData: """{app}\G25Standalone.exe"" --quiet"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\G25Standalone.exe"; Description: "Start G25Standalone now"; Flags: nowait postinstall skipifsilent

[Code]
function RunControl(const Parameters: String): Boolean;
var
  ExitCode: Integer;
begin
  Result := Exec(ExpandConstant('{app}\G25Standalone.exe'), Parameters,
    ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ExitCode);
  if Result then Result := ExitCode = 0;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if FileExists(ExpandConstant('{app}\G25Standalone.exe')) then
    if not RunControl('--stop --quiet') then
      Result := 'G25Standalone could not stop safely. Close games and retry. See %LOCALAPPDATA%\G25Standalone\control.log.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    if not RunControl('--register --quiet') then begin
      RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'G25Standalone');
      RaiseException('DirectInput registration failed. See %LOCALAPPDATA%\G25Standalone\control.log. Setup did not start the controller.');
    end;
    if not WizardIsTaskSelected('autostart') then
      RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'G25Standalone');
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := False;
  if not RunControl('--stop --quiet') then begin
    MsgBox('G25Standalone could not stop safely. Close games and retry. No files were removed.', mbError, MB_OK);
    Exit;
  end;
  if not RunControl('--unregister --quiet') then begin
    MsgBox('Could not restore the previous DirectInput registration. No files were removed. See %LOCALAPPDATA%\G25Standalone\control.log.', mbError, MB_OK);
    Exit;
  end;
  Result := True;
end;
