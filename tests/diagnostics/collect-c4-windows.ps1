#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$OutputPath,
    [ValidatePattern('^[0-9a-fA-F]{40}$')][string]$SourceCommit
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $IsWindows -or
    [Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'X64' -or
    [Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -ne 'X64') {
    throw 'Windows x64 and an x64 PowerShell process are required.'
}
$PSModuleAutoLoadingPreference = 'None'
Import-Module "$PSHOME/Modules/Microsoft.PowerShell.Utility/Microsoft.PowerShell.Utility.psd1"

function Read-Entry([string]$Path) {
    try { $attributes = [IO.File]::GetAttributes($Path) }
    catch [IO.FileNotFoundException] { return @{ status = 'missing' } }
    catch [IO.DirectoryNotFoundException] { return @{ status = 'missing' } }
    $directory = ($attributes -band [IO.FileAttributes]::Directory) -ne 0
    $link = ($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    $target = $null
    if ($link) {
        $item = if ($directory) { [IO.DirectoryInfo]::new($Path) } else { [IO.FileInfo]::new($Path) }
        $target = $item.LinkTarget
    }
    return [ordered]@{
        status = 'present'
        kind = if ($link) { 'reparsePoint' } elseif ($directory) { 'directory' } else { 'file' }
        linkTarget = $target
    }
}

function Read-LocalEntry([string]$Path) {
    $normalized = $Path.Replace('\', '/')
    if ($normalized -notmatch '^[A-Za-z]:/' -or $normalized.Substring(2).Contains(':')) {
        return @{ status = 'unavailable'; reason = 'notAbsoluteLocalPath' }
    }
    $full = [IO.Path]::GetFullPath($normalized).Replace('\', '/').TrimEnd('/')
    $root = $full.Substring(0, 2) + '/'
    if ([IO.DriveInfo]::new($root).DriveType -ne [IO.DriveType]::Fixed) {
        return @{ status = 'unavailable'; reason = 'notFixedLocalDrive' }
    }
    $cursor = $root
    $entry = Read-Entry $cursor
    foreach ($part in $full.Substring(2).Split('/', [StringSplitOptions]::RemoveEmptyEntries)) {
        if ($entry.status -ne 'present') { return $entry }
        if ($entry.kind -eq 'reparsePoint') {
            return @{ status = 'unavailable'; reason = 'reparsePointAncestor' }
        }
        $cursor = $cursor.TrimEnd('/') + '/' + $part
        $entry = Read-Entry $cursor
    }
    return $entry
}

if ($OutputPath.Replace('\', '/') -notmatch '^[A-Za-z]:/' -or
    [IO.Path]::GetExtension($OutputPath) -ine '.json') {
    throw 'OutputPath must be an absolute local .json path.'
}
$output = [IO.Path]::GetFullPath($OutputPath)
$parent = Read-LocalEntry ([IO.Path]::GetDirectoryName($output))
if ($parent.status -ne 'present' -or $parent.kind -ne 'directory') {
    throw 'The output parent must be an existing local directory without reparse points.'
}
if ((Read-LocalEntry $output).status -ne 'missing') { throw 'The output path is not a new local file.' }

$names = @(
    'gh', 'jq', 'uv', 'go', 'node', 'dotnet', 'bun', 'pnpm', 'tsc', 'typescript-language-server',
    'kubelogin', 'cosign', 'cue', 'helm', 'kubectl', 'kustomize', 'sqlc', 'terraform', 'trivy', 'yq',
    'op', 'bat', 'cargo-make', 'fzf', 'ghq', 'gitleaks', 'golangci-lint', 'lefthook', 'rg', 'shellcheck', 'zoxide'
)
$scriptCommands = @('pnpm', 'tsc', 'tsserver', 'typescript-language-server')
$sdkRoots = [ordered]@{
    'go/bin' = 'go'
    'node' = 'node'
    'dotnet' = 'dotnet'
    'pnpm' = 'pnpm'
    'typescript-cli/node_modules/.bin' = 'tsc'
    'typescript-lsp/node_modules/.bin' = 'tsserver'
    'typescript-language-server/node_modules/.bin' = 'typescript-language-server'
}
$stableBin = $HOME.Replace('\', '/').TrimEnd('/') + '/.local/bin'
$sdkBase = $HOME.Replace('\', '/').TrimEnd('/') + '/.local/share/chezmoi-dotfiles'
$inventory = @(
    foreach ($name in $names) {
        $extensions = if ($name -in $scriptCommands) { @('.exe', '.cmd', '.ps1', '') } else { @('.exe') }
        foreach ($extension in $extensions) {
            $path = "$stableBin/$name$extension"
            [ordered]@{ command = $name; root = 'stableBin'; path = $path; observation = (Read-LocalEntry $path) }
        }
    }
)
$sdkInventory = @(
    foreach ($key in $sdkRoots.Keys) {
        $rootPath = "$sdkBase/$key"
        $name = $sdkRoots[$key]
        $extensions = if ($name -in $scriptCommands) { @('.exe', '.cmd', '.ps1', '') } else { @('.exe') }
        [ordered]@{
            root = "sdk:$key"
            path = $rootPath
            observation = (Read-LocalEntry $rootPath)
            command = $name
            commandRole = if ($name -eq 'tsserver') { 'auxiliary' } else { 'primary' }
            entrypoints = @(
                foreach ($extension in $extensions) {
                    $path = "$rootPath/$name$extension"
                    [ordered]@{ path = $path; observation = (Read-LocalEntry $path) }
                }
            )
        }
    }
)

$safeDirectories = [Collections.Generic.List[string]]::new()
$resolutionBlock = $null
$firstBlockedPathElement = $null
$processPath = [Environment]::GetEnvironmentVariable('PATH', 'Process')
$pathElements = ([string]$processPath).Split(';')
for ($index = 0; $index -lt $pathElements.Count; $index++) {
    if ($pathElements[$index] -eq '') { continue }
    $path = $pathElements[$index].Trim('"').Replace('\', '/')
    $entry = Read-LocalEntry $path
    if ($entry.status -eq 'missing') { continue }
    if ($entry.status -eq 'unavailable') { $resolutionBlock = $entry.reason }
    elseif ($entry.kind -ne 'directory') { $resolutionBlock = 'nonDirectoryOrLinkedPathElement' }
    if ($resolutionBlock) {
        $firstBlockedPathElement = [ordered]@{ index = $index; reason = $resolutionBlock }
        break
    }
    $safeDirectories.Add($path.TrimEnd('/'))
}
$searchExtensions = @('', '.exe', '.com', '.cmd', '.bat', '.ps1')
$pathExtBlock = $null
foreach ($extension in ([string][Environment]::GetEnvironmentVariable('PATHEXT', 'Process')).Split(';')) {
    if ($extension -eq '') { continue }
    if ($extension -notmatch '^\.[A-Za-z0-9]+$') { $pathExtBlock = 'unsupportedPathExt'; break }
    if ($extension -notin $searchExtensions) { $searchExtensions += $extension }
}
if (-not $resolutionBlock) { $resolutionBlock = $pathExtBlock }
$commands = @(
    foreach ($name in $names) {
        $blocked = $resolutionBlock
        $blockingCandidateInventory = $null
        if (-not $blocked) {
            foreach ($directory in $safeDirectories) {
                foreach ($extension in $searchExtensions) {
                    $candidatePath = "$directory/$name$extension"
                    $entry = Read-Entry $candidatePath
                    if ($entry.status -eq 'present' -and $entry.kind -eq 'reparsePoint') {
                        $blocked = 'reparsePointCommandCandidate'
                        $blockingCandidateInventory = [ordered]@{ path = $candidatePath; observation = $entry }
                        break
                    }
                }
                if ($blocked) { break }
            }
        }
        $matches = @()
        if (-not $blocked) {
            try { $found = @(Get-Command -Name $name -All -ListImported -ErrorAction Stop) }
            catch [System.Management.Automation.CommandNotFoundException] { $found = @() }
            $matches = @(
                foreach ($command in $found) {
                    $match = [ordered]@{ name = $command.Name; commandType = [string]$command.CommandType }
                    if ($command.CommandType -in @('Application', 'ExternalScript')) {
                        $match.path = $command.Path.Replace('\', '/')
                    }
                    $match
                }
            )
        }
        [ordered]@{
            name = $name
            status = if ($blocked) { 'unavailable' } elseif ($matches.Count) { 'resolved' } else { 'notFound' }
            reason = $blocked
            matchesInPrecedenceOrder = $matches
            blockingCandidateInventory = $blockingCandidateInventory
        }
    }
)
$report = [ordered]@{
    schemaVersion = 1
    collectedAtUtc = [DateTime]::UtcNow.ToString('o')
    script = [ordered]@{
        sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
        distributionSourceCommit = if ($SourceCommit) { $SourceCommit.ToLowerInvariant() } else { $null }
        sourceCommitMeaning = 'Caller-supplied distribution revision, not an integration revision or verified provenance.'
    }
    system = [ordered]@{
        osDescription = [Runtime.InteropServices.RuntimeInformation]::OSDescription
        osArchitecture = [string][Runtime.InteropServices.RuntimeInformation]::OSArchitecture
        processArchitecture = [string][Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture
        logicalProcessorCount = [Environment]::ProcessorCount
    }
    powershell = [ordered]@{ version = $PSVersionTable.PSVersion.ToString(); edition = $PSVersionTable.PSEdition }
    observation = [ordered]@{
        scope = 'Current PowerShell process. Launch with pwsh -NoProfile -File; profile loading is not verified.'
        toolVersionsExecuted = $false
        sandboxAssessed = $false
        limitations = @(
            'Fixed inventory is not command resolution or proof of a complete installation.'
            'No target executables, shims, package managers, alias targets or function bodies are executed.'
            'Full PATH/PATHEXT values are not included; blocking candidate paths are inventory only.'
            'Unsafe PATH elements block resolution; linked command candidates block that command.'
            'Paths are point-in-time observations, not protection against concurrent filesystem changes.'
        )
    }
    commandDiscoverySafety = [ordered]@{
        pathElementIndexBase = 0
        firstBlockedPathElement = $firstBlockedPathElement
        pathExtBlockReason = $pathExtBlock
    }
    commandResolution = $commands
    fixedEntrypoints = $inventory
    sdkRoots = $sdkInventory
}
$bytes = [Text.UTF8Encoding]::new($false).GetBytes(($report | ConvertTo-Json -Depth 12) + [Environment]::NewLine)
$stream = [IO.File]::Open($output, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $stream.Write($bytes, 0, $bytes.Length) }
finally { $stream.Dispose() }
