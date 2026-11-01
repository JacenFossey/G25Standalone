param(
    [string]$Python = 'python',
    [string]$CMake = '',
    [string]$ISCC = '',
    [string]$Version = '0.2.0',
    [switch]$SkipInstaller
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}

if ($Version -notmatch '^\d+\.\d+\.\d+([-.][A-Za-z0-9.]+)?$') { throw 'Invalid version.' }
if (-not $CMake) {
    $command = Get-Command cmake -ErrorAction SilentlyContinue
    if ($command) { $CMake = $command.Source }
    else {
        $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
        if (Test-Path $vswhere) {
            $vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
            $CMake = Join-Path $vs 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
        }
    }
}
if (-not $CMake -or -not (Test-Path -LiteralPath $CMake)) { throw 'CMake not found. Install VS C++ tools or pass -CMake.' }
if (-not $SkipInstaller) {
    if (-not $ISCC) {
        $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($command) { $ISCC = $command.Source }
        else { $ISCC = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
    }
    if (-not (Test-Path -LiteralPath $ISCC)) { throw 'Inno Setup 6 not found. Pass -ISCC or use -SkipInstaller for a folder bundle.' }
}

Push-Location $root
try {
    Invoke-Checked $Python @('-m', 'unittest', 'discover', '-s', 'tests', '-v')
    & (Join-Path $root 'tests\test_registration.ps1')
    Invoke-Checked $CMake @('-S', 'native/g25ff', '-B', 'build/g25ff-x86', '-A', 'Win32')
    Invoke-Checked $CMake @('--build', 'build/g25ff-x86', '--config', 'Release')
    Invoke-Checked $CMake @('-S', 'native/g25ff', '-B', 'build/g25ff-x64', '-A', 'x64')
    Invoke-Checked $CMake @('--build', 'build/g25ff-x64', '--config', 'Release')
    Invoke-Checked $Python @('-m', 'PyInstaller', '--noconfirm', '--clean', 'packaging/G25Standalone.spec')
    $previousAppData = $env:LOCALAPPDATA
    try {
        # Keep smoke-test logs out of the user's live controller settings/logs.
        $env:LOCALAPPDATA = Join-Path $root 'build\package-smoke'
        Invoke-Checked (Join-Path $root 'dist\G25Standalone\G25Standalone.exe') @('--check-package', '--quiet')
    }
    finally { $env:LOCALAPPDATA = $previousAppData }
    if (-not $SkipInstaller) {
        Invoke-Checked $ISCC @("/DAppVersion=$Version", 'installer/G25Standalone.iss')
    }
}
finally { Pop-Location }
