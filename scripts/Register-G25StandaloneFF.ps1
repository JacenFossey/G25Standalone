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

if ($Action -eq 'Install') {
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'G25Standalone currently targets 64-bit Windows.'
    }
    if (-not $Dll32 -or -not $Dll64) {
        throw 'Pass both -Dll32 and -Dll64 paths.'
    }
    if (Test-Path $stateFile) {
        throw 'G25Standalone DirectInput registration already exists. Uninstall it first.'
    }

    $resolved32 = (Resolve-Path $Dll32).Path
    $resolved64 = (Resolve-Path $Dll64).Path
    New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null
    $backup = Join-Path $stateRoot ('backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    New-Item -ItemType Directory -Force -Path $backup | Out-Null

    $state = [ordered]@{
        version = 1
        backup = $backup
        oem32 = (Test-Key ([Microsoft.Win32.RegistryView]::Registry32) $oemPath)
        oem64 = (Test-Key ([Microsoft.Win32.RegistryView]::Registry64) $oemPath)
        com32 = (Test-Key ([Microsoft.Win32.RegistryView]::Registry32) $comPath)
        com64 = (Test-Key ([Microsoft.Win32.RegistryView]::Registry64) $comPath)
    }

    foreach ($bits in 32,64) {
        if ($state."oem$bits") {
            & reg.exe export "HKCU\$oemPath" (Join-Path $backup "oem-$bits.reg") /y "/reg:$bits" | Out-Null
        }
        if ($state."com$bits") {
            & reg.exe export "HKCU\$comPath" (Join-Path $backup "com-$bits.reg") /y "/reg:$bits" | Out-Null
        }
    }

    $state | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8

    Set-Registration ([Microsoft.Win32.RegistryView]::Registry32) $resolved32
    Set-Registration ([Microsoft.Win32.RegistryView]::Registry64) $resolved64

    Write-Host 'G25Standalone DirectInput FFB registered for 32-bit and 64-bit games.'
    Write-Host 'Restart any games that were already open.'
    exit 0
}

if (-not (Test-Path $stateFile)) {
    throw 'No G25Standalone DirectInput registration state was found.'
}

$state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
foreach ($bits in 32,64) {
    $view = if ($bits -eq 32) {
        [Microsoft.Win32.RegistryView]::Registry32
    } else {
        [Microsoft.Win32.RegistryView]::Registry64
    }

    Remove-Key $view $comPath
    Remove-Key $view $oemPath

    if ($state."com$bits") {
        & reg.exe import (Join-Path $state.backup "com-$bits.reg") "/reg:$bits" | Out-Null
    }
    if ($state."oem$bits") {
        & reg.exe import (Join-Path $state.backup "oem-$bits.reg") "/reg:$bits" | Out-Null
    }
}

Remove-Item -LiteralPath $stateFile
Write-Host 'G25Standalone DirectInput FFB registration removed and previous state restored.'
