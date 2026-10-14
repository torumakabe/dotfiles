# Run only through the native Windows Copilot powershell tool, one call per Step.
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Root,
    [Parameter(Mandatory)] [ValidateSet('control', 'candidate')] [string] $Mode,
    [Parameter(Mandatory)] [ValidateSet(1, 2)] [int] $Step
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$PSNativeCommandArgumentPassing = 'Standard'
if (-not $IsWindows -or $PSVersionTable.PSVersion -lt [version]'7.3') {
    throw 'Requires native Windows PowerShell 7.3 or later inside the sandbox.'
}
$manifest = Get-Content -LiteralPath (Join-Path $Root 'manifest.json') -Raw |
    ConvertFrom-Json -AsHashtable
$evidence = Join-Path $manifest['workspace'] "evidence\$Mode"
$resultPath = Join-Path $evidence "step-$Step.json"
if (Test-Path -LiteralPath $resultPath) { throw 'This step already has evidence; do not overwrite it.' }
$result = [ordered]@{
    schema = 1; trialId = $manifest['trialId']; mode = $Mode; step = $Step
    invocationId = [guid]::NewGuid().ToString(); processId = $PID
    status = 'failed'; probes = @(); stage = 'preconditions'
    runtimeSandboxAttribution = 'unverified'; removalDecision = 'pending'
}
function Normalize-Path([string] $Value) {
    $Value = [Environment]::ExpandEnvironmentVariables($Value).Replace('/', '\')
    if ($Value.StartsWith('~\')) { $Value = Join-Path $HOME $Value.Substring(2) }
    if (-not [IO.Path]::IsPathFullyQualified($Value) -or $Value -match '[*?]') {
        throw 'Non-comparable path; the result must remain pending.'
    }
    return [IO.Path]::GetFullPath($Value).TrimEnd('\').ToLowerInvariant()
}
function Is-Under([string] $Child, [string] $Parent) {
    $c = Normalize-Path $Child
    $p = Normalize-Path $Parent
    return $c -eq $p -or $c.StartsWith($p + '\')
}
function Run-Native([string] $Name, [string] $Exe, [string[]] $Arguments) {
    $lines = @(& $Exe @Arguments 2>&1)
    $code = $LASTEXITCODE
    $text = ($lines | ForEach-Object { $_.ToString() }) -join "`n"
    $category = if ($code -eq 0) { $null }
        elseif ($text -match '(?i)denied|permission|0x80070005') { 'permission' }
        elseif ($text -match '(?i)download|network|connect|tls|certificate|resolve') { 'network-or-resolution' }
        elseif ($text -match '(?i)python|interpreter') { 'python' }
        else { 'native-command-failed' }
    $result.probes += @{ name = $Name; exitCode = $code; status = $(if ($code -eq 0) { 'passed' } else { 'failed' }); error = $category }
    if ($code -ne 0) { throw "$Name failed ($category, exit $code); raw stderr was not logged." }
    return $text.Trim()
}
try {
    $launch = Get-Content -LiteralPath (Join-Path $evidence 'launch.json') -Raw |
        ConvertFrom-Json -AsHashtable
    if ($launch['mode'] -ne $Mode -or $launch['parentCacheOverridePresent'] -ne $false -or
        ($Mode -eq 'candidate' -and $launch['parentHelperPresent'] -ne $false)) {
        throw 'The CLI parent environment is not the intended comparison condition.'
    }
    $result.cliVersion = $launch['cliVersion']
    $result.osBuild = $manifest['osBuild']
    $modeInfo = $manifest['modes'][$Mode]
    foreach ($file in $modeInfo['supportHashes'].Keys) {
        $path = Join-Path $modeInfo['home'] "hooks\$file"
        if ((Get-FileHash -LiteralPath $path).Hash -ne $modeInfo['supportHashes'][$file]) {
            throw 'The copied Guard policy, launcher, or interpreter record changed.'
        }
    }
    foreach ($file in @('copilot-guard.py', 'uv-enforcer.py')) {
        $path = Join-Path $modeInfo['home'] "hooks\scripts\$file"
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne
            $modeInfo['hookHashes'][$file]) {
            throw "The copied $file differs from the prepared trial."
        }
    }
    $configured = Get-Content -LiteralPath (Join-Path $evidence 'cli-configured-sandbox.json') -Raw |
        ConvertFrom-Json -AsHashtable
    if ($configured['enabled'] -ne $true -or $configured['allowDevToolAccess'] -ne $true) {
        throw 'The CLI did not load the prepared sandbox and developer-tool settings.'
    }
    $result.cliSandboxSettingsLoaded = $true
    if ((Normalize-Path (Get-Location).Path) -ne (Normalize-Path $manifest['workspace'])) {
        throw 'Run from the empty trial workspace, not the repository.'
    }
    foreach ($name in @('UV_CONFIG_FILE', 'UV_NO_CACHE', 'UV_NO_CONFIG',
        'UV_WORKING_DIR', 'UV_PROJECT', 'UV_ENV_FILE', 'UV_PROJECT_ENVIRONMENT')) {
        if ([Environment]::GetEnvironmentVariable($name, 'Process')) {
            throw "Explicit override detected inside the tool: $name"
        }
    }
    $configPaths = [Collections.Generic.List[string]]::new()
    foreach ($item in $manifest['uvConfigurationFiles']) { $configPaths.Add($item['path']) }
    $configPaths.Add((Join-Path $env:APPDATA 'uv\uv.toml'))
    $configPaths.Add((Join-Path $env:PROGRAMDATA 'uv\uv.toml'))
    foreach ($path in $configPaths | Select-Object -Unique) {
        if ((Test-Path -LiteralPath $path -PathType Leaf) -and
            (Get-Content -LiteralPath $path -Raw) -match '(?m)^\s*(cache-dir|no-cache)\s*=') {
            throw "Explicit cache configuration detected: $path"
        }
    }
    $result.stage = 'cache-discovery'
    $result.uvVersion = Run-Native 'uv-version' 'uv' @('--version')
    $cache = Run-Native 'uv-cache-dir' 'uv' @('cache', 'dir')
    $cache = [IO.Path]::GetFullPath($cache)
    $result.cachePath = $cache
    $result.sandboxUvCacheEnvironmentPresent =
        -not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable('UV_CACHE_DIR', 'Process'))
    if ($env:UV_CACHE_DIR -and (Normalize-Path $env:UV_CACHE_DIR) -ne (Normalize-Path $cache)) {
        throw 'uv cache dir disagrees with the command environment.'
    }
    if ($Mode -eq 'control' -and (Normalize-Path $cache) -ne
        (Normalize-Path $manifest['oldCachePath'])) { throw 'Control is not using the dedicated cache.' }
    if ($Mode -eq 'candidate') {
        $result.cacheUnderWorkspace = Is-Under $cache $manifest['workspace']
        $result.cacheUnderLegacyGrant = Is-Under $cache $manifest['oldCachePath']
        $result.cacheCoveredByConfiguredWriteGrant = @(
            $modeInfo['configuredSandbox']['userPolicy']['filesystem']['readwritePaths'] |
            Where-Object { Is-Under $cache $_ }
        ).Count -gt 0
        $result.cacheUnderTemp = Is-Under $cache $env:TEMP
    }
    $owned = Join-Path $cache ('.dotfiles-uv-trial-' + $manifest['trialId'] + '-' + $Mode)
    $result.probeOwnedDirectory = $owned
    $marker = Join-Path $owned 'cross-command.txt'
    $result.stage = 'atomic-rename'
    if ($Step -eq 1) {
        if (Test-Path -LiteralPath $owned) { throw 'The trial cache directory already exists.' }
        New-Item -ItemType Directory -Path $owned | Out-Null
        [IO.File]::WriteAllText($marker, ($manifest['trialId'] + ':' + $Mode))
    } else {
        $first = Get-Content -LiteralPath (Join-Path $evidence 'step-1.json') -Raw |
            ConvertFrom-Json -AsHashtable
        if ($first['status'] -ne 'technical-success' -or $first['trialId'] -ne $manifest['trialId'] -or
            (Normalize-Path $first['cachePath']) -ne (Normalize-Path $cache) -or
            [IO.File]::ReadAllText($marker) -ne ($manifest['trialId'] + ':' + $Mode)) {
            throw 'The first tool call did not leave the same persistent cache marker.'
        }
        $result.previousInvocationId = $first['invocationId']
        $result.crossCommandMarker = 'passed'
    }
    $source = Join-Path $owned "step-$Step.before"
    $target = Join-Path $owned "step-$Step.after"
    [IO.File]::WriteAllText($source, 'synthetic-rename-payload')
    [IO.File]::Move($source, $target)
    if ([IO.File]::ReadAllText($target) -ne 'synthetic-rename-payload') {
        throw 'Renamed file content differs.'
    }
    $result.probes += @{ name = 'same-directory-atomic-rename'; status = 'passed'; exitCode = 0; error = $null }
    $result.stage = 'uv-package-run'
    $code = @'
import json, pathlib, subprocess, sys, idna
cache = subprocess.run(["uv", "cache", "dir"], check=True, capture_output=True, text=True).stdout.strip()
print(json.dumps({"package":"idna","version":idna.__version__,"pythonVersion":sys.version.split()[0],
                  "pythonExecutable":sys.executable,"pythonPrefix":sys.prefix,
                  "uvCacheDir":str(pathlib.Path(cache).resolve())}))
'@
    $arguments = @('run', '--no-project', '--isolated', '--no-python-downloads',
        '--python', $manifest['pythonPath'], '--with', 'idna==3.10')
    if ($Step -eq 2) { $arguments += '--offline' }
    else { $arguments += @('--refresh-package', 'idna') }
    $arguments += @('python', '-c', $code)
    $packageOutput = Run-Native 'uv-run-idna' 'uv' $arguments
    # uv writes progress to stderr; retain only the payload's JSON line.
    $jsonLines = @($packageOutput -split "`n" | Where-Object { $_.Trim().StartsWith('{"package":') })
    if ($jsonLines.Count -ne 1) { throw 'Package payload did not produce exactly one JSON result.' }
    $package = $jsonLines[0] | ConvertFrom-Json -AsHashtable
    if ($package['version'] -ne '3.10' -or
        (Normalize-Path $package['uvCacheDir']) -ne (Normalize-Path $cache) -or
        -not (Is-Under $package['pythonPrefix'] $cache)) {
        throw 'The actual uv-run environment/package did not use the discovered cache.'
    }
    $result.package = $package
    $result.status = 'technical-success'
    $result.stage = 'complete'
    $result.runtimeSandboxAttribution = 'unverified'
    $result.removalDecision = 'pending-runtime-sandbox-attribution'
} catch {
    $result.probes += @{
        name = $result.stage; status = 'failed'; exitCode = 1
        error = $_.Exception.GetType().FullName
    }
    $result.error = @{ type = $_.Exception.GetType().FullName; message = $_.Exception.Message }
    $result | ConvertTo-Json -Depth 25 | Set-Content -LiteralPath $resultPath -Encoding utf8
    Write-Error ("Trial failed at " + $result.stage + ". Evidence: " + $resultPath) -ErrorAction Continue
    exit 1
}
$result | ConvertTo-Json -Depth 25 | Set-Content -LiteralPath $resultPath -Encoding utf8
$result | ConvertTo-Json -Depth 25
exit 0
