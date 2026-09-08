#requires -Version 7.6
[CmdletBinding()]
param([Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedCommit)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $IsWindows) {
    Write-Host 'BLOCKED: Windows native PowerShell is required. No fixture was created.'
    exit 2
}
$commit = & git -C $PSScriptRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $commit -cne $ExpectedCommit) { throw 'Commit mismatch; nothing executed.' }
$changes = & git -C $PSScriptRoot status --porcelain=v1 --untracked-files=all
if ($LASTEXITCODE -ne 0 -or @($changes).Count -ne 0) { throw 'Working tree is not clean; nothing executed.' }
$output = Join-Path $PSScriptRoot 'native-result-01'
if (Test-Path -LiteralPath $output) { throw 'Existing result directory. Do not rerun or overwrite it.' }
$null = New-Item -ItemType Directory -Path $output
$phase = 'audit-read-preflight'
$status = 'BLOCKED'
$failure = $null
$native = $null
$childExit = $null
try {
    # This permission is required by the recovery engine; do not elevate to obtain it.
    $audit = Get-Acl -LiteralPath $PSScriptRoot -Audit
    if (@($audit.Audit).Count -ne 0 -or $audit.GetSecurityDescriptorSddlForm(
            [Security.AccessControl.AccessControlSections]::Audit) -match 'S:') {
        throw 'SACL is unsupported. No fixture was created.'
    }
    $phase = 'native-fixture'
    Write-Host 'Windows fixture running. Existing mise/profile/PATH/settings are not being changed.'
    $pwsh = (Get-Process -Id $PID).Path
    & $pwsh -NoLogo -NoProfile -NonInteractive -File (Join-Path $PSScriptRoot 'rehearse-windows-uv.ps1') `
        -NativeRoot (Join-Path $output 'fixture') `
        1> (Join-Path $output 'native.stdout.json') 2> (Join-Path $output 'native.stderr.txt')
    $childExit = $LASTEXITCODE
    if ($childExit -ne 0) { throw "Native fixture returned $childExit. See native.stderr.txt and native.stdout.json." }
    $native = Get-Content -LiteralPath (Join-Path $output 'native.stdout.json') -Raw | ConvertFrom-Json -AsHashtable
    $cases = @($native.cases | Where-Object kind -eq 'native_fixture_not_install')
    if ($native.status -ne 'native_fixture_passed_not_install' -or $native.nativeExecuted -ne $true -or
        $cases.Count -ne 11 -or @($cases | Where-Object status -ne 'passed').Count -ne 0) {
        throw 'Native case results do not meet the required eleven cases.'
    }
    $status = 'PASS'
} catch {
    $failure = $_.Exception.Message
    if ($phase -eq 'native-fixture') { $status = 'FAIL' }
    Write-Host "$status`: $failure"
}
@{
    status=$status; phase=$phase; failure=$failure; childExitCode=$childExit
    commit=$commit
    powerShell=$PSVersionTable.PSVersion.ToString()
    architecture=[Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    scope='Dedicated fixture only. No real install, migration, profile/PATH or authentication change.'
    native=$native
} | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $output 'result.json') -Encoding utf8
if ($status -eq 'PASS') { Write-Host 'PASS: Eleven native fixture cases completed. Real migration has not run.' }
Write-Host "Result: $(Join-Path $output 'result.json')"
if ($status -eq 'PASS') { exit 0 }
if ($status -eq 'BLOCKED') { exit 2 }
exit 1
