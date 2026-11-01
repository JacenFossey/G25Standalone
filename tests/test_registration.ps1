# Mocked registration transaction tests: never read/write the real registry.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\Register-G25StandaloneFF.ps1')
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('g25-registration-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$stateRoot = $testRoot
$stateFile = Join-Path $testRoot 'directinput-registration.json'
$Dll32 = Join-Path $testRoot '32.dll'
$Dll64 = Join-Path $testRoot '64.dll'
New-Item -ItemType File -Path $Dll32,$Dll64 | Out-Null

function Assert($condition, [string]$message) { if (-not $condition) { throw "ASSERT: $message" } }
function Expect-Failure([scriptblock]$body) {
    $failed = $false
    try { & $body } catch { $failed = $true }
    Assert $failed 'expected failure'
}

# Save the real restore helper to test ordering with fake registry operations.
$realRestore = ${function:Restore-Snapshot}
$realOwnership = ${function:Assert-OwnedRegistration}
$realLive = ${function:Test-LiveRegistration}
# Override every helper that could otherwise reach HKCU, even in no-op/error paths.
$script:oemId = $clsid
$script:hasComClass = $true
function Test-Key($view, $path) { return $script:hasComClass }
function Get-FFClassId($view) { return $script:oemId }
function Open-HKCU($view) {
    $key = [PSCustomObject]@{}
    $key | Add-Member ScriptMethod GetValue { param($name) return 'C:\mock\g25ff.dll' }
    $key | Add-Member ScriptMethod Dispose { }
    $base = [PSCustomObject]@{ Key = $key }
    $base | Add-Member ScriptMethod OpenSubKey { param($path, $write) return $this.Key }
    $base | Add-Member ScriptMethod Dispose { }
    return $base
}
& $realOwnership
$script:oemId = '{00000000-0000-0000-0000-000000000001}'
Expect-Failure { & $realOwnership }
$script:hasComClass = $false
Assert (-not (& $realLive)) 'unrelated registration is not ours'
$script:oemId = $clsid
Assert (& $realLive) 'OEM association alone detects orphaned registration'
$script:operations = [System.Collections.Generic.List[string]]::new()
function Remove-Key($view, $path) { $script:operations.Add('remove') }
function Invoke-Reg($Arguments) { $script:operations.Add('import') }
$fixture = @{ version=1; backup=$testRoot; oem32=$true; oem64=$true; com32=$true; com64=$true }
foreach ($kind in 'oem','com') {
    foreach ($bits in 32,64) { New-Item -ItemType File -Path (Join-Path $testRoot "$kind-$bits.reg") | Out-Null }
}
& $realRestore $fixture
Assert (($script:operations -join ',') -eq 'remove,remove,remove,remove,import,import,import,import') 'remove both views before importing shared OEM keys'
Remove-Item (Join-Path $testRoot 'oem-32.reg')
$script:operations.Clear()
Expect-Failure { & $realRestore $fixture }
Assert ($script:operations.Count -eq 0) 'missing backup must fail before removal'

$script:snapshots = @{}
$script:registry = 'original'
$script:failWrite = $false
$script:failRestore = $false
$script:writeCount = 0
function Assert-OwnedRegistration { }
$script:liveRegistration = $false
function Test-LiveRegistration { return $script:liveRegistration }
function New-Snapshot {
    $backup = Join-Path $stateRoot ([Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $backup | Out-Null
    $script:snapshots[$backup] = $script:registry
    return [ordered]@{ version=1; backup=$backup; oem32=$false; oem64=$false; com32=$false; com64=$false }
}
function Restore-Snapshot($snapshot) {
    if ($script:failRestore) { $script:failRestore = $false; throw 'mock import failure' }
    $script:registry = $script:snapshots[$snapshot.backup]
}
function Set-Registration($view, $dll) {
    $script:writeCount++
    $script:registry = "registered-$dll"
    if ($script:failWrite -and $script:writeCount -eq 2) { throw 'mock x64 registration failure' }
}

try {
    $Action = 'Install'
    Invoke-Registration
    Assert (Test-Path $stateFile) 'first install saves original backup'
    $originalState = Get-Content $stateFile -Raw
    Invoke-Registration
    Assert ((Get-Content $stateFile -Raw) -eq $originalState) 'upgrade preserves original backup'
    $beforeFailure = $script:registry
    $Action = 'Uninstall'
    $script:failRestore = $true
    Expect-Failure { Invoke-Registration }
    Assert ($script:registry -eq $beforeFailure) 'failed uninstall rolls back current registration'
    Assert (Test-Path $stateFile) 'failed uninstall retains state'
    Invoke-Registration
    Assert ($script:registry -eq 'original') 'uninstall restores pre-first-install state'
    Assert (-not (Test-Path $stateFile)) 'successful uninstall removes state'
    Invoke-Registration  # idempotent no-op, entirely mocked
    $script:liveRegistration = $true
    Expect-Failure { Invoke-Registration }
    $Action = 'Install'
    $beforeMissingState = $script:registry
    Expect-Failure { Invoke-Registration }
    Assert ($script:registry -eq $beforeMissingState) 'missing-state reinstall does not replace baseline'
    Assert (-not (Test-Path $stateFile)) 'missing state is not invented or removed'
    $script:liveRegistration = $false

    $Action = 'Install'
    $script:writeCount = 0
    $script:failWrite = $true
    Expect-Failure { Invoke-Registration }
    Assert ($script:registry -eq 'original') 'failed install restores registry'
    Assert (-not (Test-Path $stateFile)) 'failed install removes fresh state after rollback'
    Write-Output 'Mocked registration tests passed (no registry access).'
}
finally { Remove-Item -LiteralPath $testRoot -Recurse }
