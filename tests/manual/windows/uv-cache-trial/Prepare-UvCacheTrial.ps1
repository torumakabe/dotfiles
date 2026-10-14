# Prepare isolated copies or launch one trial from an ordinary Windows terminal.
# Never run this script through a Copilot shell tool.
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidateSet('Prepare', 'Launch')] [string] $Action,
    [Parameter(Mandatory)] [string] $Root,
    [ValidateSet('control', 'candidate')] [string] $Mode = 'control',
    [string] $SourceCopilotHome = (Join-Path $HOME '.copilot'),
    [string] $PythonPath,
    [string] $OldCachePath = $env:COPILOT_DOTFILES_UV_CACHE_DIR
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$PSNativeCommandArgumentPassing = 'Standard'
if (-not $IsWindows -or $PSVersionTable.PSVersion -lt [version]'7.3') {
    throw 'Requires native Windows and PowerShell 7.3 or later.'
}
if (-not [IO.Path]::IsPathFullyQualified($Root) -or $Root.StartsWith('\\') -or
    $Root -match '[`$"\r\n]') {
    throw 'Root must be a fully qualified local path.'
}
$Root = [IO.Path]::GetFullPath($Root).TrimEnd('\')
$ancestor = [IO.DirectoryInfo]::new($Root)
while ($null -ne $ancestor) {
    if ($ancestor.Exists -and ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Trial path must not pass through a reparse point.'
    }
    if (Test-Path -LiteralPath (Join-Path $ancestor.FullName '.git')) {
        throw 'Choose a trial path outside every Git checkout.'
    }
    $ancestor = $ancestor.Parent
}

function Normalize-Path([string] $Value) {
    $Value = [Environment]::ExpandEnvironmentVariables($Value).Replace('/', '\')
    if ($Value.StartsWith('~\')) { $Value = Join-Path $HOME $Value.Substring(2) }
    if (-not [IO.Path]::IsPathFullyQualified($Value) -or $Value -match '[*?]') {
        throw 'Policy contains a non-comparable path; review it manually.'
    }
    return [IO.Path]::GetFullPath($Value).TrimEnd('\').ToLowerInvariant()
}
function Write-Json([string] $Path, $Object) {
    $Object | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $Path -Encoding utf8
}
function Get-PolicyPaths($Filesystem, [string] $Name) {
    if ($null -eq $Filesystem) { throw 'Missing user filesystem settings.' }
    if ($null -eq $Filesystem[$Name]) { return }
    foreach ($item in @($Filesystem[$Name])) {
        if ($item -isnot [string] -or [string]::IsNullOrWhiteSpace($item) -or
            $item -match '[\r\n]') { throw "Invalid filesystem entry: $Name" }
        $item
    }
}
function Select-Sandbox($Value) {
    return @{
        enabled = $Value['enabled']; allowBypass = $Value['allowBypass']
        allowDevToolAccess = $Value['allowDevToolAccess']
        addCurrentWorkingDirectory = $Value['addCurrentWorkingDirectory']
        sandboxMcpServers = $Value['sandboxMcpServers']; sandboxLspServers = $Value['sandboxLspServers']
        userPolicy = @{ filesystem = @{
            readwritePaths = @(Get-PolicyPaths $Value['userPolicy']['filesystem'] 'readwritePaths')
            readonlyPaths = @(Get-PolicyPaths $Value['userPolicy']['filesystem'] 'readonlyPaths')
            deniedPaths = @(Get-PolicyPaths $Value['userPolicy']['filesystem'] 'deniedPaths')
        } }
    }
}
function Assert-NoExplicitUvOverride {
    foreach ($name in @('UV_CONFIG_FILE', 'UV_NO_CACHE', 'UV_NO_CONFIG',
        'UV_WORKING_DIR', 'UV_PROJECT', 'UV_ENV_FILE', 'UV_PROJECT_ENVIRONMENT')) {
        foreach ($scope in @('Process', 'User', 'Machine')) {
            if ([Environment]::GetEnvironmentVariable($name, $scope)) {
                throw "Explicit override detected: $name ($scope); classification is pending."
            }
        }
    }
    foreach ($scope in @('User', 'Machine')) {
        if ([Environment]::GetEnvironmentVariable('UV_CACHE_DIR', $scope)) {
            throw "Persistent UV_CACHE_DIR detected ($scope); do not change it automatically."
        }
    }
}
function Find-UvConfiguration([string] $Directory) {
    $paths = [Collections.Generic.List[string]]::new()
    $cursor = [IO.DirectoryInfo]::new($Directory)
    while ($null -ne $cursor) {
        $paths.Add((Join-Path $cursor.FullName 'uv.toml'))
        $paths.Add((Join-Path $cursor.FullName 'pyproject.toml'))
        $cursor = $cursor.Parent
    }
    $paths.Add((Join-Path $env:APPDATA 'uv\uv.toml'))
    $paths.Add((Join-Path $env:PROGRAMDATA 'uv\uv.toml'))
    foreach ($path in $paths | Select-Object -Unique) {
        $exists = Test-Path -LiteralPath $path -PathType Leaf
        if ($exists -and (Get-Content -LiteralPath $path -Raw) -match
            '(?m)^\s*(cache-dir|no-cache)\s*=') {
            throw "Cache configuration detected in $path; review TOML and hold the trial."
        }
        [ordered]@{ path = $path; exists = $exists }
    }
}
function Invoke-HookCheck([string] $HomePath, [string] $Command) {
    $payload = @{ toolName = 'powershell'; toolArgs = @{ command = $Command } } |
        ConvertTo-Json -Compress
    $global:LASTEXITCODE = 0
    $lines = @($payload | & (Join-Path $HomePath 'hooks\run-hook.ps1') 'uv-enforcer.py')
    if ($LASTEXITCODE -ne 0) { throw 'Pinned hook launcher failed during preparation.' }
    $text = $lines -join "`n"
    if ($text.Trim()) { return ($text | ConvertFrom-Json -AsHashtable) }
    return @{}
}

$manifestPath = Join-Path $Root 'manifest.json'
if ($Action -eq 'Prepare') {
    Assert-NoExplicitUvOverride
    if (Test-Path -LiteralPath $Root) { throw 'Root already exists; use a new trial directory.' }
    $hooksSource = Join-Path $SourceCopilotHome 'hooks'
    $runtime = @{}
    $runtimePath = Join-Path $hooksSource 'python-runtime.env'
    if (-not (Test-Path -LiteralPath $runtimePath -PathType Leaf)) {
        throw 'The installed hook runtime record is missing.'
    }
    foreach ($line in Get-Content -LiteralPath $runtimePath) {
        if ($line -match '^(python_root|python)=(.+)$') {
            if ($runtime.ContainsKey($Matches[1])) { throw 'Duplicate hook runtime record.' }
            $runtime[$Matches[1]] = $Matches[2]
        }
    }
    if (-not $runtime['python_root'] -or -not $runtime['python'] -or
        -not (Test-Path -LiteralPath $runtime['python_root'] -PathType Container) -or
        -not (Test-Path -LiteralPath $runtime['python'] -PathType Leaf)) {
        throw 'The existing managed Python recorded by python-runtime.env is unavailable.'
    }
    if (-not $PythonPath) { $PythonPath = $runtime['python'] }
    if ((Normalize-Path $PythonPath) -ne (Normalize-Path $runtime['python'])) {
        throw 'PythonPath must match the interpreter already recorded by python-runtime.env.'
    }
    $PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
    $found = @(& uv python find --no-project --no-python-downloads $PythonPath)
    if ($LASTEXITCODE -ne 0 -or (Normalize-Path ($found -join '').Trim()) -ne
        (Normalize-Path $PythonPath)) { throw 'uv cannot find the exact installed Python.' }
    if (-not $OldCachePath) { throw 'The current dedicated cache helper is absent.' }
    $oldKey = Normalize-Path $OldCachePath
    $rootKey = Normalize-Path $Root
    $profileTrialRoot = Normalize-Path (Join-Path $env:LOCALAPPDATA 'CopilotUvCacheTrials')
    if (-not $rootKey.StartsWith($profileTrialRoot + '\')) {
        throw 'Trial path must be below the current user profile local app data trial directory.'
    }
    foreach ($excluded in @($oldKey, (Normalize-Path $env:TEMP),
        (Normalize-Path $SourceCopilotHome))) {
        if ($rootKey -eq $excluded -or $rootKey.StartsWith($excluded + '\')) {
            throw 'Trial path must be outside TEMP, the existing cache, and the source Copilot home.'
        }
    }
    try {
        $settings = Get-Content -LiteralPath (Join-Path $SourceCopilotHome 'settings.json') -Raw |
            ConvertFrom-Json -AsHashtable
    } catch {
        throw 'Source settings could not be read as strict JSON; their contents were not printed.'
    }
    $sandbox = $settings['sandbox']
    if ($sandbox['enabled'] -ne $true -or $sandbox['allowDevToolAccess'] -ne $true -or
        $sandbox['addCurrentWorkingDirectory'] -ne $true) {
        throw 'Source must enable sandbox, developer-tool access, and working-directory access.'
    }
    $rw = @(Get-PolicyPaths $sandbox['userPolicy']['filesystem'] 'readwritePaths')
    if (-not @($rw | Where-Object { (Normalize-Path $_) -eq $oldKey }).Count) {
        throw 'Source does not contain the exact dedicated-cache write grant.'
    }
    $candidateRw = @($rw | Where-Object { (Normalize-Path $_) -ne $oldKey })
    foreach ($path in $candidateRw) {
        $key = Normalize-Path $path
        if ($oldKey.StartsWith($key + '\') -or $key.StartsWith($oldKey + '\')) {
            throw 'Another user write grant overlaps the legacy cache; hold rather than remove it.'
        }
    }
    $configurationFiles = @(Find-UvConfiguration (Join-Path $Root 'workspace'))
    if (((Get-Item -LiteralPath $hooksSource).Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        @(Get-ChildItem -LiteralPath $hooksSource -Recurse -Force |
        Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw 'Source hooks contain a reparse point; review rather than follow it.'
    }
    $hooks = Get-Content -LiteralPath (Join-Path $hooksSource 'hooks.json') -Raw |
        ConvertFrom-Json -AsHashtable
    $branch = @'
    if tool_name == "powershell" and not command.startswith(WINDOWS_UV_CACHE_PREFIX):
        print(
            json.dumps(
                {
                    "modifiedArgs": {
                        **tool_args,
                        "command": WINDOWS_UV_CACHE_PREFIX + command,
                    }
                }
            )
        )

'@
    $uvSource = Get-Content -LiteralPath (Join-Path $hooksSource 'scripts\uv-enforcer.py') -Raw
    $uvSource = $uvSource.Replace("`r`n", "`n")
    $branch = $branch.Replace("`r`n", "`n")
    if ($uvSource.Split($branch, [StringSplitOptions]::None).Count -ne 2) {
        throw 'Installed enforcer differs from the reviewed branch; do not guess a replacement.'
    }
    New-Item -ItemType Directory -Path $Root -ErrorAction Stop | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $Root 'workspace\evidence'), (Join-Path $Root 'code') |
        Out-Null
    foreach ($file in @('Test-UvCacheSandbox.ps1', 'Trace-UvCacheHook.ps1')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination (Join-Path $Root 'code')
    }
    $manifest = [ordered]@{
        schema = 1; trialId = [guid]::NewGuid().ToString(); root = $Root
        workspace = (Join-Path $Root 'workspace'); pythonPath = $PythonPath
        oldCachePath = $oldKey
        uvConfigurationFiles = $configurationFiles; modes = @{}
        osBuild = [Environment]::OSVersion.Version.ToString()
    }
    $manifest.cliVersion = (@(& copilot --no-auto-update --version) -join "`n")
    if ($LASTEXITCODE -ne 0) { throw 'CLI version query failed.' }
    $manifest.uvVersion = (@(& uv --version) -join "`n")
    if ($LASTEXITCODE -ne 0) { throw 'uv version query failed.' }
    foreach ($variant in @('control', 'candidate')) {
        $homePath = Join-Path $Root "$variant\.copilot"
        $hooksPath = Join-Path $homePath 'hooks'
        $evidencePath = Join-Path $Root "workspace\evidence\$variant"
        New-Item -ItemType Directory -Path "$hooksPath\scripts", $evidencePath | Out-Null
        foreach ($file in @('hooks.json', 'run-hook.ps1', 'run-hook.sh', 'python-runtime.env',
            'allowed-files.txt', 'blocked-files.txt', 'ask-files.txt')) {
            Copy-Item -LiteralPath (Join-Path $hooksSource $file) -Destination $hooksPath
        }
        Get-ChildItem -LiteralPath "$hooksSource\scripts" -Filter '*.py' -File |
            Copy-Item -Destination "$hooksPath\scripts"
        (Get-Item -LiteralPath "$hooksPath\hooks.json" -Force).IsReadOnly = $false
        if ($variant -eq 'candidate') {
            (Get-Item -LiteralPath "$hooksPath\scripts\uv-enforcer.py" -Force).IsReadOnly = $false
            [IO.File]::WriteAllText("$hooksPath\scripts\uv-enforcer.py",
                $uvSource.Replace($branch, ''), [Text.UTF8Encoding]::new($false))
        }
        $copy = $settings | ConvertTo-Json -Depth 40 | ConvertFrom-Json -AsHashtable
        $copy['sandbox']['allowBypass'] = $false
        if ($variant -eq 'candidate') {
            $copy['sandbox']['userPolicy']['filesystem']['readwritePaths'] = $candidateRw
        }
        $ro = @(Get-PolicyPaths $copy['sandbox']['userPolicy']['filesystem'] 'readonlyPaths')
        $copy['sandbox']['userPolicy']['filesystem']['readonlyPaths'] =
            @($ro + $homePath + (Join-Path $Root 'code') + $manifestPath +
                $runtime['python_root'] | Select-Object -Unique)
        Write-Json "$homePath\settings.json" $copy
        $hookCopy = $hooks | ConvertTo-Json -Depth 20 | ConvertFrom-Json -AsHashtable
        foreach ($event in $hookCopy['hooks'].Keys) {
            foreach ($hook in $hookCopy['hooks'][$event]) {
                if ($hook['powershell'] -notmatch 'run-hook\.ps1.*?([\w-]+\.py)\s*$') {
                    throw 'Unsupported hook registration; manual isolation review is required.'
                }
                $script = $Matches[1]
                if ($event -eq 'preToolUse' -and $script -in @('copilot-guard.py', 'uv-enforcer.py')) {
                    $hook['powershell'] = '& "' + (Join-Path $Root 'code\Trace-UvCacheHook.ps1') +
                        '" -Launcher "' + "$hooksPath\run-hook.ps1" + '" -ScriptName "' + $script +
                        '" -EvidencePath "' + "$evidencePath\hook-events.jsonl" + '"'
                } else {
                    $hook['powershell'] = '& "' + "$hooksPath\run-hook.ps1" + '" ' + $script
                }
                $hook['bash'] = '"' + "$hooksPath\run-hook.sh".Replace('\', '/') + '" ' + $script
            }
        }
        $names = @($hookCopy['hooks']['preToolUse'] | ForEach-Object { $_['powershell'] })
        foreach ($required in @('copilot-guard.py', 'uv-enforcer.py')) {
            if (@($names | Where-Object { $_.Contains($required) }).Count -ne 1) {
                throw 'Guard and uv enforcer must each be registered exactly once.'
            }
        }
        Write-Json "$hooksPath\hooks.json" $hookCopy
        foreach ($command in @('python script.py', 'pip install example')) {
            if ((Invoke-HookCheck $homePath $command)['permissionDecision'] -ne 'deny') {
                throw 'The direct Python/pip prohibition did not survive isolation.'
            }
        }
        $allowed = Invoke-HookCheck $homePath 'uv --version'
        if ($variant -eq 'control' -and -not $allowed.ContainsKey('modifiedArgs')) {
            throw 'Control does not demonstrate cache injection.'
        }
        if ($variant -eq 'candidate' -and $allowed.ContainsKey('modifiedArgs')) {
            throw 'Candidate still rewrites the command.'
        }
        $hashes = @{}
        foreach ($file in @('copilot-guard.py', 'uv-enforcer.py')) {
            $hashes[$file] = (Get-FileHash -LiteralPath "$hooksPath\scripts\$file" -Algorithm SHA256).Hash
        }
        $supportHashes = @{}
        foreach ($file in @('allowed-files.txt', 'blocked-files.txt', 'ask-files.txt',
            'python-runtime.env', 'run-hook.ps1')) {
            $hash = (Get-FileHash -LiteralPath (Join-Path $hooksPath $file)).Hash
            if ($hash -ne (Get-FileHash -LiteralPath (Join-Path $hooksSource $file)).Hash) {
                throw 'A copied policy/launcher/runtime file changed.'
            }
            $supportHashes[$file] = $hash
        }
        $manifest.modes[$variant] = @{
            home = $homePath; hookHashes = $hashes; supportHashes = $supportHashes
            configuredSandbox = (Select-Sandbox $copy['sandbox']); directPythonAndPipDenied = $true
        }
    }
    $sourceGuardHash = (Get-FileHash -LiteralPath "$hooksSource\scripts\copilot-guard.py").Hash
    if ($manifest.modes.control.hookHashes['copilot-guard.py'] -ne $sourceGuardHash -or
        $manifest.modes.candidate.hookHashes['copilot-guard.py'] -ne $sourceGuardHash) {
        throw 'Guard source changed while copying.'
    }
    Write-Json $manifestPath $manifest
    Write-Output "Prepared: $manifestPath"
    exit 0
}

# Launch affects this terminal process and its child only; restore it on return.
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json -AsHashtable
Assert-NoExplicitUvOverride
$homePath = $manifest['modes'][$Mode]['home']
$saved = @{}
foreach ($name in @('COPILOT_HOME', 'UV_CACHE_DIR', 'COPILOT_DOTFILES_UV_CACHE_DIR',
    'COPILOT_AUDIT_DIR', 'COPILOT_ALLOW_ALL')) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:COPILOT_HOME = $homePath
    [Environment]::SetEnvironmentVariable('UV_CACHE_DIR', $null, 'Process')
    [Environment]::SetEnvironmentVariable('COPILOT_ALLOW_ALL', $null, 'Process')
    if ($Mode -eq 'control') { $env:COPILOT_DOTFILES_UV_CACHE_DIR = $manifest['oldCachePath'] }
    else { [Environment]::SetEnvironmentVariable('COPILOT_DOTFILES_UV_CACHE_DIR', $null, 'Process') }
    $env:COPILOT_AUDIT_DIR = Join-Path $Root "workspace\evidence\$Mode"
    $configured = @(& copilot --no-auto-update config sandbox) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'CLI did not load sandbox configuration from the trial home.' }
    $loaded = $configured | ConvertFrom-Json -AsHashtable
    if ($loaded['enabled'] -ne $true -or $loaded['allowBypass'] -ne $false -or
        $loaded['allowDevToolAccess'] -ne $true) { throw 'Loaded sandbox settings are not the trial settings.' }
    $planned = $manifest['modes'][$Mode]['configuredSandbox']
    foreach ($flag in @('enabled', 'allowBypass', 'allowDevToolAccess',
        'addCurrentWorkingDirectory', 'sandboxMcpServers', 'sandboxLspServers')) {
        if ($loaded[$flag] -ne $planned[$flag]) { throw "Loaded setting differs: $flag" }
    }
    foreach ($name in @('readwritePaths', 'readonlyPaths', 'deniedPaths')) {
        $actual = @(Get-PolicyPaths $loaded['userPolicy']['filesystem'] $name | Sort-Object) |
            ConvertTo-Json -Compress
        $expected = @($planned['userPolicy']['filesystem'][$name] | Sort-Object) |
            ConvertTo-Json -Compress
        if ($actual -cne $expected) { throw "Loaded filesystem setting differs: $name" }
    }
    Write-Json (Join-Path $Root "workspace\evidence\$Mode\cli-configured-sandbox.json") (Select-Sandbox $loaded)
    Write-Json (Join-Path $Root "workspace\evidence\$Mode\launch.json") @{
        parentCacheOverridePresent = $false; mode = $Mode; home = $homePath
        parentHelperPresent = -not [string]::IsNullOrEmpty($env:COPILOT_DOTFILES_UV_CACHE_DIR)
        cliVersion = (@(& copilot --no-auto-update --version) -join "`n")
    }
    & copilot -C $manifest['workspace'] --no-auto-update
    $cliExit = $LASTEXITCODE
} finally {
    foreach ($name in $saved.Keys) {
        [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
    }
}
exit $cliExit
