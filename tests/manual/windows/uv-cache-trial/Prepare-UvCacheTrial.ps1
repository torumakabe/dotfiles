# Prepare isolated copies or launch one trial from an ordinary Windows terminal.
# Never run this script through a Copilot shell tool.
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidateSet('Prepare', 'Prompt', 'Launch')] [string] $Action,
    [Parameter(Mandatory)] [string] $Root,
    [ValidateSet('control', 'candidate')] [string] $Mode = 'control',
    [string] $SourceCopilotHome = (Join-Path $HOME '.copilot'),
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
$manifestPath = Join-Path $Root 'workspace\trial.json'
if ($Action -eq 'Prepare') {
    if (Test-Path -LiteralPath $Root) { throw 'Root already exists; use a new trial directory.' }
    $hostUvCommand = Get-Command uv -ErrorAction Stop
    if ($hostUvCommand.CommandType -ne [Management.Automation.CommandTypes]::Application) {
        throw 'The usual terminal resolves uv through a PowerShell alias/function, not an application; preserve it and stop for review.'
    }
    $hostUvPath = [IO.Path]::GetFullPath($hostUvCommand.Source)
    $hostUvVersion = (@(uv --version) -join "`n")
    if ($LASTEXITCODE -ne 0) { throw 'The resolved uv executable could not run.' }
    $cacheHome = if ($env:COPILOT_CACHE_HOME) {
        if (-not [IO.Path]::IsPathFullyQualified($env:COPILOT_CACHE_HOME)) {
            throw 'COPILOT_CACHE_HOME is relative; runtime cache attribution cannot be derived safely.'
        }
        [IO.Path]::GetFullPath($env:COPILOT_CACHE_HOME)
    } else {
        [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'copilot'))
    }
    $runtimeUvCachePath = Join-Path $cacheHome 'sandbox\packages\uv'
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
    $guidePath = [IO.Path]::GetFullPath(
        (Join-Path $PSScriptRoot '..\..\..\..\docs\windows-uv-cache-trial.md'))
    $guide = [IO.File]::ReadAllText($guidePath)
    $promptMatches = [regex]::Matches($guide,
        '(?s)<!-- uv-cache-trial-prompt:start -->\s*```text\r?\n(.*?)\r?\n```\s*<!-- uv-cache-trial-prompt:end -->')
    if ($promptMatches.Count -ne 1) { throw 'The guide must contain exactly one trial prompt template.' }
    $promptTemplate = $promptMatches[0].Groups[1].Value
    New-Item -ItemType Directory -Path $Root -ErrorAction Stop | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $Root 'workspace\evidence') | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Test-UvCacheSandbox.py') `
        -Destination (Join-Path $Root 'workspace')
    $manifest = [ordered]@{
        schema = 2; trialId = [guid]::NewGuid().ToString()
        workspace = (Join-Path $Root 'workspace')
        hostUv = @{ path = $hostUvPath; version = $hostUvVersion }
        runtimeUvCachePath = $runtimeUvCachePath
        runtimeCachePathBasisCliVersion = '1.0.98-0'
        oldCachePath = $oldKey; modes = @{}
        osBuild = [Environment]::OSVersion.Version.ToString()
    }
    $manifest.cliVersion = (@(& copilot --no-auto-update --version) -join "`n")
    if ($LASTEXITCODE -ne 0) { throw 'CLI version query failed.' }
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
        if ($variant -eq 'candidate') {
            (Get-Item -LiteralPath "$hooksPath\scripts\uv-enforcer.py" -Force).IsReadOnly = $false
            [IO.File]::WriteAllText("$hooksPath\scripts\uv-enforcer.py",
                $uvSource.Replace($branch, ''), [Text.UTF8Encoding]::new($false))
        }
        $copy = $settings | ConvertTo-Json -Depth 40 | ConvertFrom-Json -AsHashtable
        if ($variant -eq 'candidate') {
            $copy['sandbox']['userPolicy']['filesystem']['readwritePaths'] = $candidateRw
        }
        $ro = @(Get-PolicyPaths $copy['sandbox']['userPolicy']['filesystem'] 'readonlyPaths')
        $copy['sandbox']['userPolicy']['filesystem']['readonlyPaths'] =
            @($ro + $homePath + $runtime['python_root'] | Select-Object -Unique)
        Write-Json "$homePath\settings.json" $copy
        $names = @($hooks['hooks']['preToolUse'] | ForEach-Object { $_['powershell'] })
        foreach ($required in @('copilot-guard.py', 'uv-enforcer.py')) {
            if (@($names | Where-Object { $_.Contains($required) }).Count -ne 1) {
                throw 'Guard and uv enforcer must each be registered exactly once.'
            }
        }
        $prompt = $promptTemplate.Replace('<Root>', $Root).Replace('<Mode>', $variant)
        if ($prompt -match '<(?:Root|Mode)>') {
            throw 'Generated prompt still contains a trial placeholder.'
        }
        $runCommands = @([regex]::Matches($prompt, '(?m)^uv run [^\r\n]+$') |
            ForEach-Object { $_.Value })
        if ($runCommands.Count -ne 2 -or
            $runCommands[0] -notmatch 'python \.\\Test-UvCacheSandbox\.py --mode ' -or
            $runCommands[0] -notmatch '--step 1$' -or
            $runCommands[0] -match '--offline' -or
            $runCommands[1] -notmatch 'python \.\\Test-UvCacheSandbox\.py --mode ' -or
            $runCommands[1] -notmatch '--step 2$' -or
            $runCommands[1] -notmatch '--offline') {
            throw 'Generated measurements must call bare uv directly for both separate steps.'
        }
        [IO.File]::WriteAllText((Join-Path $Root "$variant-prompt.txt"),
            $prompt, [Text.UTF8Encoding]::new($false))
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
        foreach ($command in $runCommands) {
            $checked = Invoke-HookCheck $homePath $command
            if ($checked['permissionDecision'] -eq 'deny') {
                throw 'The original uv policy rejected a generated measurement command.'
            }
            if ($variant -eq 'control') {
                if (-not $checked.ContainsKey('modifiedArgs') -or
                    -not $checked['modifiedArgs']['command'].EndsWith($command)) {
                    throw 'Control must retain the generated command after its automatic cache prefix.'
                }
            } elseif ($checked.ContainsKey('modifiedArgs')) {
                throw 'Candidate must not rewrite a generated measurement command.'
            }
        }
        $manifest.modes[$variant] = @{
            home = $homePath
            readwritePaths = @(Get-PolicyPaths $copy['sandbox']['userPolicy']['filesystem'] 'readwritePaths')
            configuredSandbox = (Select-Sandbox $copy['sandbox'])
        }
    }
    Write-Json $manifestPath $manifest
    Write-Output "Prepared: $manifestPath"
    exit 0
}

# Launch affects this terminal process and its child only; restore it on return.
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json -AsHashtable
if ($Action -eq 'Prompt') {
    if ((Normalize-Path $manifest['workspace']) -ne (Normalize-Path (Join-Path $Root 'workspace'))) {
        throw 'Trial workspace differs from the prepared record.'
    }
    Write-Output ([IO.File]::ReadAllText((Join-Path $Root "$Mode-prompt.txt")))
    exit 0
}
$homePath = $manifest['modes'][$Mode]['home']
$saved = @{}
foreach ($name in @('COPILOT_HOME', 'COPILOT_DOTFILES_UV_CACHE_DIR',
    'COPILOT_AUDIT_DIR', 'COPILOT_ALLOW_ALL')) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:COPILOT_HOME = $homePath
    [Environment]::SetEnvironmentVariable('COPILOT_ALLOW_ALL', $null, 'Process')
    if ($Mode -eq 'control') { $env:COPILOT_DOTFILES_UV_CACHE_DIR = $manifest['oldCachePath'] }
    else { [Environment]::SetEnvironmentVariable('COPILOT_DOTFILES_UV_CACHE_DIR', $null, 'Process') }
    $env:COPILOT_AUDIT_DIR = Join-Path $Root "workspace\evidence\$Mode"
    $configured = @(& copilot --no-auto-update config sandbox) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'CLI did not load sandbox configuration from the trial home.' }
    $loaded = $configured | ConvertFrom-Json -AsHashtable
    if ($loaded['enabled'] -ne $true -or $loaded['allowDevToolAccess'] -ne $true) {
        throw 'Loaded sandbox settings are not the trial settings.'
    }
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
    $evidencePath = Join-Path $Root "workspace\evidence\$Mode"
    foreach ($name in @('launch.json', 'uv-resolution.json', 'step-1.json', 'step-2.json')) {
        if (Test-Path -LiteralPath (Join-Path $evidencePath $name)) {
            throw 'This mode already has evidence; do not overwrite it. Prepare a new trial root.'
        }
    }
    Write-Json (Join-Path $evidencePath 'launch.json') @{
        mode = $Mode; sandboxSettingsLoaded = $true; home = $homePath
        parentUvCacheOverridePresent = -not [string]::IsNullOrEmpty(
            [Environment]::GetEnvironmentVariable('UV_CACHE_DIR', 'Process'))
        helperEnabled = $Mode -eq 'control'
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
