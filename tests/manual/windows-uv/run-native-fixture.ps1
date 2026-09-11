#requires -Version 7.6
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedCommit,
    [Parameter(Mandatory)][ValidatePattern('^native-result-[0-9]{2,}$')][string]$ResultDirectory,
    [string]$CaseName
)
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
$output = Join-Path $PSScriptRoot $ResultDirectory
if (Test-Path -LiteralPath $output) { throw 'Existing result directory. Do not rerun or overwrite it.' }
$null = New-Item -ItemType Directory -Path $output
$phase = 'native-fixture'
$status = 'BLOCKED'
$failure = $null
$native = $null
$childExit = $null
try {
    Write-Host 'Windows fixture running. Existing mise/profile/PATH/settings are not being changed.'
    $pwsh = (Get-Process -Id $PID).Path
    & $pwsh -NoLogo -NoProfile -NonInteractive -File (Join-Path $PSScriptRoot 'rehearse-windows-uv.ps1') `
        -NativeRoot (Join-Path $output 'fixture') -CaseName $CaseName `
        1> (Join-Path $output 'native.stdout.json') 2> (Join-Path $output 'native.stderr.txt')
    $childExit = $LASTEXITCODE
    $text = Get-Content -LiteralPath (Join-Path $output 'native.stdout.json') -Raw
    if (-not [string]::IsNullOrWhiteSpace($text)) { $native = $text | ConvertFrom-Json -AsHashtable }
    if ($childExit -ne 0) { throw "Native fixture returned $childExit. See native.stderr.txt and native.stdout.json." }
    if ($null -eq $native) { throw 'Native fixture returned no JSON result.' }
    $cases = @($native.cases | Where-Object kind -eq 'native_fixture_not_install')
    $expectedCases = if ($CaseName) { 1 } else { 80 }
    if ($native.status -ne 'native_fixture_passed_not_install' -or $native.nativeExecuted -ne $true -or
        $native.sacl -ne 'unobserved' -or $native.count -ne ($expectedCases + 5) -or
        $cases.Count -ne $expectedCases -or $native.selectedCase -cne $CaseName -or
        @($native.cases | Where-Object status -ne 'passed').Count -ne 0 -or
        ($CaseName -and $cases[0].case -cne $CaseName)) {
        throw "Native results do not meet the required $expectedCases fixture and five static checks."
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
    sacl='unobserved'; selectedCase=$CaseName; native=$native
} | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $output 'result.json') -Encoding utf8
if ($status -eq 'PASS') { Write-Host "PASS: $expectedCases native fixture cases completed. SACL unobserved. Real migration has not run." }
Write-Host "Result: $(Join-Path $output 'result.json')"
if ($status -eq 'PASS') { exit 0 }
if ($status -eq 'BLOCKED') { exit 2 }
exit 1
