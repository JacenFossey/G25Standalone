param(
    [ValidateSet('Install','Uninstall')]
    [string]$Action = 'Install',
    [string]$Dll32 = '',
    [string]$Dll64 = ''
)

$ErrorActionPreference = 'Stop'

$clsid = '{F1571E1D-B59D-4322-BAC1-EBD860FA40D7}'
$oemPath = 'System\CurrentControlSet\Control\MediaProperties\PrivateProperties\Joystick\OEM\VID_046D&PID_C299'
$comPath = "Software\Classes\CLSID\$clsid"
$stateRoot = Join-Path $env:LOCALAPPDATA 'G25Standalone'
$stateFile = Join-Path $stateRoot 'directinput-registration.json'

function Open-HKCU([Microsoft.Win32.RegistryView]$view) {
    [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::CurrentUser,
        $view
    )
}

function Test-Key([Microsoft.Win32.RegistryView]$view, [string]$path) {
    $base = Open-HKCU $view
    try {
        $key = $base.OpenSubKey($path, $false)
        try { return $null -ne $key }
        finally { if ($key) { $key.Dispose() } }
    }
    finally { $base.Dispose() }
}

function Remove-Key([Microsoft.Win32.RegistryView]$view, [string]$path) {
    $base = Open-HKCU $view
    try { $base.DeleteSubKeyTree($path, $false) }
    finally { $base.Dispose() }
}

function DWords([uint32[]]$values) {
    $bytes = [System.Collections.Generic.List[byte]]::new()
    foreach ($value in $values) {
        $bytes.AddRange([BitConverter]::GetBytes($value))
    }
    Write-Output -NoEnumerate $bytes.ToArray()
}

function Set-Registration(
    [Microsoft.Win32.RegistryView]$view,
    [string]$dll
) {
    $base = Open-HKCU $view
    try {
        $server = $base.CreateSubKey("$comPath\InProcServer32", $true)
        try {
            $server.SetValue('', $dll, [Microsoft.Win32.RegistryValueKind]::String)
            $server.SetValue('ThreadingModel', 'Both', [Microsoft.Win32.RegistryValueKind]::String)
        }
        finally { $server.Dispose() }

        $oem = $base.CreateSubKey($oemPath, $true)
        try {
            $oem.SetValue('OEMName', 'Logitech G25 Racing Wheel USB', [Microsoft.Win32.RegistryValueKind]::String)
            # G25 native-mode joystick metadata: FFB-capable, 19 buttons, one POV.
            $oem.SetValue(
                'OEMData',
                [byte[]](0x43,0x00,0x88,0x10,0x13,0x00,0x00,0x00),
                [Microsoft.Win32.RegistryValueKind]::Binary
            )
        }
        finally { $oem.Dispose() }

        $axis = $base.CreateSubKey("$oemPath\Axes\0", $true)
        try {
            $axis.SetValue('', 'Wheel axis', [Microsoft.Win32.RegistryValueKind]::String)
            $axis.SetValue('Attributes', [byte[]](0x01,0x81,0x00,0x00), [Microsoft.Win32.RegistryValueKind]::Binary)
            $axis.SetValue('FFAttributes', [byte[]](0x0A,0x00,0x00,0x00,0x00,0x01,0x00,0x00), [Microsoft.Win32.RegistryValueKind]::Binary)
        }
        finally { $axis.Dispose() }

        $ff = $base.CreateSubKey("$oemPath\OEMForceFeedback", $true)
        try {
            $ff.SetValue('Attributes', (DWords @(0,4000,4000)), [Microsoft.Win32.RegistryValueKind]::Binary)
            $ff.SetValue('CLSID', $clsid, [Microsoft.Win32.RegistryValueKind]::String)
        }
        finally { $ff.Dispose() }

        $effects = @(
            @('{13541C20-8E33-11D0-9AD0-00A0C9A06E35}','Constant',0,0x8601,0x03ED),
            @('{13541C21-8E33-11D0-9AD0-00A0C9A06E35}','Ramp Force',1,0x8602,0x03EF),
            @('{13541C22-8E33-11D0-9AD0-00A0C9A06E35}','Square Wave',2,0x8603,0x03EF),
            @('{13541C23-8E33-11D0-9AD0-00A0C9A06E35}','Sine Wave',3,0x8603,0x03EF),
            @('{13541C24-8E33-11D0-9AD0-00A0C9A06E35}','Triangle Wave',4,0x8603,0x03EF),
            @('{13541C25-8E33-11D0-9AD0-00A0C9A06E35}','Sawtooth Up Wave',5,0x8603,0x03EF),
            @('{13541C26-8E33-11D0-9AD0-00A0C9A06E35}','Sawtooth Down Wave',6,0x8603,0x03EF),
            @('{13541C27-8E33-11D0-9AD0-00A0C9A06E35}','Spring',7,0xD804,0x036D),
            @('{13541C28-8E33-11D0-9AD0-00A0C9A06E35}','Damper',8,0xD804,0x036D),
            @('{13541C29-8E33-11D0-9AD0-00A0C9A06E35}','Inertia',9,0xD804,0x036D),
            @('{13541C2A-8E33-11D0-9AD0-00A0C9A06E35}','Friction',10,0xD804,0x036D),
            @('{13541C2B-8E33-11D0-9AD0-00A0C9A06E35}','Custom Force',11,0x8605,0x03EF)
        )

        foreach ($effect in $effects) {
            $key = $base.CreateSubKey("$oemPath\OEMForceFeedback\Effects\$($effect[0])", $true)
            try {
                $key.SetValue('', $effect[1], [Microsoft.Win32.RegistryValueKind]::String)
                $key.SetValue(
                    'Attributes',
                    (DWords @([uint32]$effect[2],[uint32]$effect[3],[uint32]$effect[4],[uint32]$effect[4],0x30)),
                    [Microsoft.Win32.RegistryValueKind]::Binary
                )
            }
            finally { $key.Dispose() }
        }
    }
    finally { $base.Dispose() }
}

function Invoke-Reg([string[]]$Arguments) {
    & "$env:SystemRoot\System32\reg.exe" @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "reg.exe failed ($LASTEXITCODE): $Arguments" }
}

function New-Snapshot {
    $backup = Join-Path $stateRoot ('backup-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    $snapshot = [ordered]@{ version = 1; backup = $backup }
    foreach ($bits in 32,64) {
        $view = if ($bits -eq 32) { [Microsoft.Win32.RegistryView]::Registry32 } else { [Microsoft.Win32.RegistryView]::Registry64 }
        foreach ($kind in 'oem','com') {
            $path = if ($kind -eq 'oem') { $oemPath } else { $comPath }
            $snapshot["$kind$bits"] = Test-Key $view $path
            if ($snapshot["$kind$bits"]) {
                Invoke-Reg @('export', "HKCU\$path", (Join-Path $backup "$kind-$bits.reg"), '/y', "/reg:$bits")
            }
        }
    }
    return $snapshot
}

function Test-Snapshot($snapshot) {
    if ($snapshot.version -ne 1 -or -not $snapshot.backup) { throw 'Invalid registration backup state.' }
    foreach ($bits in 32,64) {
        foreach ($kind in 'oem','com') {
            if ($snapshot."$kind$bits" -isnot [bool]) { throw "Invalid backup flag: $kind$bits" }
            if ($snapshot."$kind$bits" -and -not (Test-Path -LiteralPath (Join-Path $snapshot.backup "$kind-$bits.reg"))) {
                throw "Missing registry backup: $kind-$bits.reg. Registration was not removed."
            }
        }
    }
}

function Restore-Snapshot($snapshot) {
    Test-Snapshot $snapshot
    # Some HKCU OEM keys are shared between registry views. Remove both views
    # before importing either view, otherwise the second removal erases the first restore.
    foreach ($bits in 32,64) {
        $view = if ($bits -eq 32) { [Microsoft.Win32.RegistryView]::Registry32 } else { [Microsoft.Win32.RegistryView]::Registry64 }
        Remove-Key $view $comPath
        Remove-Key $view $oemPath
    }
    foreach ($bits in 32,64) {
        foreach ($kind in 'com','oem') {
            if ($snapshot."$kind$bits") {
                Invoke-Reg @('import', (Join-Path $snapshot.backup "$kind-$bits.reg"), "/reg:$bits")
            }
        }
    }
}

function Get-FFClassId([Microsoft.Win32.RegistryView]$view) {
    $base = Open-HKCU $view
    try {
        $key = $base.OpenSubKey("$oemPath\OEMForceFeedback", $false)
        try { if ($key) { return [string]$key.GetValue('CLSID') }; return '' }
        finally { if ($key) { $key.Dispose() } }
    }
    finally { $base.Dispose() }
}

function Test-LiveRegistration {
    foreach ($view in [Microsoft.Win32.RegistryView]::Registry32,[Microsoft.Win32.RegistryView]::Registry64) {
        if ((Test-Key $view $comPath) -or (Get-FFClassId $view) -eq $clsid) { return $true }
    }
    return $false
}

function Assert-OwnedRegistration {
    foreach ($view in [Microsoft.Win32.RegistryView]::Registry32,[Microsoft.Win32.RegistryView]::Registry64) {
        if ((Get-FFClassId $view) -ne $clsid) {
            throw 'The OEM force-feedback association changed outside G25Standalone. Refusing to overwrite/remove it.'
        }
        $base = Open-HKCU $view
        try {
            $server = $base.OpenSubKey("$comPath\InProcServer32", $false)
            try {
                if (-not $server -or [IO.Path]::GetFileName([string]$server.GetValue('')) -ne 'g25ff.dll') {
                    throw 'Registration changed outside G25Standalone. Refusing to overwrite/remove it; inspect the saved backup.'
                }
            }
            finally { if ($server) { $server.Dispose() } }
        }
        finally { $base.Dispose() }
    }
}

function Invoke-Registration {
if ($Action -eq 'Install') {
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'G25Standalone currently targets 64-bit Windows.'
    }
    if (-not $Dll32 -or -not $Dll64) {
        throw 'Pass both -Dll32 and -Dll64 paths.'
    }
    $resolved32 = (Resolve-Path -LiteralPath $Dll32).Path
    $resolved64 = (Resolve-Path -LiteralPath $Dll64).Path
    New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null
    $upgrading = Test-Path -LiteralPath $stateFile
    if ($upgrading) {
        $original = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
        Test-Snapshot $original
        Assert-OwnedRegistration
    }
    elseif (Test-LiveRegistration) {
        throw 'G25Standalone registration exists but its original backup state is missing. Refusing to replace it with a new baseline; recover the original backup first.'
    }
    $current = New-Snapshot
    if (-not $upgrading) {
        # Persist the original backup before touching the registry. Upgrades keep
        # this same backup so uninstall restores the pre-first-install state.
        $temporary = "$stateFile.tmp"
        $current | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $stateFile
    }
    try {
        Set-Registration ([Microsoft.Win32.RegistryView]::Registry32) $resolved32
        Set-Registration ([Microsoft.Win32.RegistryView]::Registry64) $resolved64
    }
    catch {
        Restore-Snapshot $current
        if (-not $upgrading) { Remove-Item -LiteralPath $stateFile }
        throw
    }
    if ($upgrading) { Remove-Item -LiteralPath $current.backup -Recurse }
    Write-Host 'G25Standalone DirectInput FFB registered for 32-bit and 64-bit games.'
    Write-Host 'Restart any games that were already open.'
    return
}

if (-not (Test-Path -LiteralPath $stateFile)) {
    if (Test-LiveRegistration) {
        throw 'G25Standalone registration still exists but its original backup state is missing. Refusing to unregister or remove driver files.'
    }
    Write-Host 'No G25Standalone registration to remove.'
    return
}

$original = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
Test-Snapshot $original
Assert-OwnedRegistration
$current = New-Snapshot
try { Restore-Snapshot $original }
catch {
    Restore-Snapshot $current
    throw
}
Remove-Item -LiteralPath $stateFile
Remove-Item -LiteralPath $current.backup -Recurse
# Retain the original backup as a recovery aid; settings and logs are also kept.
Write-Host 'G25Standalone DirectInput FFB registration removed and previous state restored.'
}

# Dot sourcing loads helpers for mocked tests without touching the registry.
if ($MyInvocation.InvocationName -ne '.') { Invoke-Registration }
