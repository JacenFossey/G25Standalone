param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$expectedPython = (Get-Content (Join-Path $repoRoot 'packaging/python-version.txt') -Raw).Trim()

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}

Push-Location $repoRoot
try {
    Invoke-Checked $Python @('-c', "import sys, struct; assert sys.platform == 'win32' and struct.calcsize('P') == 8 and sys.version.split()[0] == '$expectedPython', 'Build requires Windows x64 CPython $expectedPython'")
    # A fresh isolated environment prevents unrelated developer packages from
    # leaking into the executable. Every package wheel is hash checked.
    $venv = Join-Path $repoRoot 'build/bundle-venv'
    if (Test-Path $venv) { Remove-Item $venv -Recurse -Force }
    Invoke-Checked $Python @('-m', 'venv', $venv)
    $buildPython = Join-Path $venv 'Scripts/python.exe'
    Invoke-Checked $buildPython @('-m', 'pip', 'install', '--require-hashes', '--only-binary=:all:', '-r', 'packaging/requirements-build.txt')
    Invoke-Checked $buildPython @('-m', 'pip', 'check')
    foreach ($arch in @('x86', 'x64')) {
        $generatorArch = if ($arch -eq 'x86') { 'Win32' } else { 'x64' }
        Invoke-Checked 'cmake' @('-S', 'native/g25ff', '-B', "build/bundle-g25ff-$arch", '-A', $generatorArch)
        Invoke-Checked 'cmake' @('--build', "build/bundle-g25ff-$arch", '--config', 'Release')
    }
    Invoke-Checked $buildPython @('-m', 'PyInstaller', '--noconfirm', '--clean', '--workpath', 'build/pyinstaller', '--distpath', 'build/frozen', 'packaging/G25Standalone.spec')
    Invoke-Checked $buildPython @('packaging/build_bundle.py')
} finally {
    Pop-Location
}
