#requires -Version 7.6
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Plan')][string]$Command,
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$SourceCommit,
    [Parameter(Mandatory)][string]$Config,
    [Parameter(Mandatory)][string]$Data,
    [Parameter(Mandatory)][string]$Cache,
    [Parameter(Mandatory)][string]$Recovery,
    [Parameter(Mandatory)][string]$Report,
    [Parameter(Mandatory)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$ExpectedVersion,
    [switch]$WritersStopped
)
. (Join-Path $PSScriptRoot 'uv-state.ps1')

function ConvertTo-DirectPath([string]$Path) {
    $path = [regex]::Replace($Path.Replace('/','\'), '\\+', '\')
    Assert-Path $path -Absent
    return $path
}
function Assert-DirectEnvironment {
    foreach ($variable in @(Get-ChildItem Env:)) {
        if ($variable.Name -in @('GIT_DIR','GIT_WORK_TREE','GIT_COMMON_DIR','GIT_INDEX_FILE',
                'GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES') -or
            ($variable.Name -like 'MISE_*' -and
                -not ($variable.Name -ieq 'MISE_SHELL' -and $variable.Value -ceq 'pwsh'))) {
            throw "Environment override requires review: $($variable.Name)"
        }
    }
}
function Assert-DirectSource([string]$Root, [string]$Commit, [string]$ScriptRoot = $PSScriptRoot) {
    if ($Commit -cnotmatch '^[0-9a-fA-F]{40}$') { throw 'SourceCommit requires the full Git SHA.' }
    Assert-DirectEnvironment
    $git = (Get-Command git -CommandType Application -TotalCount 1 -ErrorAction Stop).Source
    $actualRoot = (Invoke-Captured $git @('--no-optional-locks','rev-parse','--show-toplevel') $Root).stdout.Trim()
    Assert-Equal (ConvertTo-DirectPath $actualRoot).ToLowerInvariant() $Root.ToLowerInvariant() 'Source must be the worktree root.'
    $head = (Invoke-Captured $git @('--no-optional-locks','rev-parse','HEAD') $Root).stdout.Trim()
    if ($head -ine $Commit) { throw 'Source HEAD differs from SourceCommit.' }
    Assert-DirectCleanSource $git $Root
    foreach ($name in @('plan-direct-windows-uv.ps1','uv-state.ps1')) {
        $pinned = Join-Path $Root "tests\manual\windows-uv\$name"
        Assert-Path $pinned
        Assert-Equal (Get-Hash $pinned) (Get-Hash (Join-Path $ScriptRoot $name)) 'Running script differs from pinned source.'
    }
}
function Assert-DirectCleanSource([string]$Git, [string]$Root) {
    $status = (Invoke-Captured $Git @('--no-optional-locks','status','--porcelain=v1',
        '--untracked-files=no','--ignore-submodules=none') $Root).stdout
    if ($status.Length) { throw 'Source has tracked changes; do not reset or rebaseline it.' }
    $untracked = (Invoke-Captured $Git @('--no-optional-locks','ls-files','--others','--exclude-standard') $Root).stdout
    foreach ($path in @($untracked -split '\r?\n' | Where-Object { $_.Length })) {
        if ($path -cnotmatch '^tests/manual/windows-uv/native-result-[0-9]{2,}/') {
            throw 'Source has untracked changes outside retained native results.'
        }
    }
}
function Assert-DirectLock($Original, $Candidate, [string]$Version) {
    if ($Original.tools.Count -ne 31 -or $Candidate.tools.Count -ne 31) { throw 'Expected 31 locked tools.' }
    $entries = @($Candidate.tools.uv)
    if ($entries.Count -ne 2) { throw 'Expected two options-distinct uv lock entries.' }
    $platforms = @($entries | ForEach-Object { $_.Keys } |
        Where-Object { $_ -like 'platforms.*' } | Sort-Object)
    Assert-Equal $platforms @('platforms.linux-arm64','platforms.linux-x64','platforms.macos-arm64',
        'platforms.windows-arm64','platforms.windows-x64') 'Unexpected candidate platforms.'
    $originalPlatforms = @($Original.tools.uv | ForEach-Object { $_.Keys } |
        Where-Object { $_ -like 'platforms.*' } | Sort-Object)
    Assert-Equal $originalPlatforms $platforms 'Original platform set differs from candidate.'
    foreach ($old in @($Original.tools.uv)) {
        if ($old.version -cne $Version -or $old.backend -cne 'aqua:astral-sh/uv') {
            throw 'Original lock must describe the same requested version on aqua.'
        }
    }
    foreach ($entry in $entries) {
        if ($entry.version -cne $Version -or $entry.backend -cne 'github:astral-sh/uv') {
            throw 'Candidate lock must describe the same requested version on GitHub.'
        }
        if ($entry.ContainsKey('platforms.windows-arm64')) {
            Assert-Equal $entry.options @{asset_pattern='uv-x86_64-pc-windows-msvc.zip'} 'Missing Windows ARM64 x64 override.'
        } elseif ($entry.ContainsKey('options')) { throw 'Unexpected standard uv lock options.' }
        foreach ($platform in @($entry.Keys | Where-Object { $_ -like 'platforms.*' })) {
            $previous = @($Original.tools.uv | Where-Object { $_.ContainsKey($platform) })
            if ($previous.Count -ne 1) { throw "Missing or ambiguous original platform: $platform" }
            foreach ($field in @('url','checksum','provenance')) {
                if (-not $entry[$platform].ContainsKey($field) -or -not $previous[0][$platform].ContainsKey($field)) {
                    throw "Missing asset verification field: $platform/$field"
                }
                Assert-Equal $entry[$platform][$field] $previous[0][$platform][$field] "Asset changed: $platform/$field"
            }
        }
    }
    # 公開予定のlockは元の30ツールを保持し、uvのブロックだけを置換する。
    $result = Get-Json $Original | ConvertFrom-Json -AsHashtable
    $result.tools.uv = $entries
    Assert-Equal (Get-WithoutUv $result.tools) (Get-WithoutUv $Original.tools) 'Non-uv locks changed.'
    return $result
}
function Get-DirectCandidateConfig($Original, $UvDeclaration) {
    if ($Original.tools.Count -ne 31 -or $Original.tools.uv -cne 'latest') {
        throw 'Expected 31 declarations and the existing uv latest setting.'
    }
    if ($Original.ContainsKey('tool_alias') -and $Original.tool_alias.ContainsKey('uv') -and
        $Original.tool_alias.uv -cne 'aqua:astral-sh/uv') {
        throw 'Unexpected explicit original uv backend.'
    }
    # registry既定のaquaも許可する。実際のbackendと版は元lockで別途照合する。
    $result = Get-Json $Original | ConvertFrom-Json -AsHashtable
    if (-not $result.ContainsKey('tool_alias')) { $result.tool_alias=@{} }
    $result.tools.uv=$UvDeclaration
    $result.tool_alias.uv='github:astral-sh/uv'
    return $result
}
function Get-DirectAliasNames([string[]]$Versions, $Configuration) {
    $names = @('latest')
    foreach ($version in $Versions) {
        if ($version -cnotmatch '^\d+\.\d+\.\d+$') { throw 'Unsupported version name.' }
        $parts = $version.Split('.')
        $names += $parts[0], ($parts[0] + '.' + $parts[1])
    }
    if ($Configuration.ContainsKey('alias') -and $Configuration.alias.ContainsKey('uv')) {
        foreach ($key in $Configuration.alias.uv.Keys) {
            if ($key -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$' -or $key.EndsWith('.')) {
                throw 'Unsupported custom uv alias name.'
            }
            $names += $key
        }
    }
    return @($names | Sort-Object -Unique)
}
function Get-DirectSlot([string]$Path, [string[]]$Versions) {
    $tree = Read-Tree $Path
    if ($tree.kind -eq 'absent') { return @{state=$tree; classification='absent'} }
    if ($tree.kind -ne 'file') {
        return @{state=$tree; classification='blocked_directory'; reason='Never replace a real directory in an alias slot.'}
    }
    $size = (Get-Item -LiteralPath $Path -Force).Length
    if ($size -gt 4096) { return @{state=$tree; classification='blocked_nonpointer'} }
    $text = [IO.File]::ReadAllText($Path).Trim()
    # 内容だけではmiseのpointerと断定しない。通常ファイルの実測値を後続レビューへ渡す。
    if ($text -notin $Versions) {
        if ($text -cmatch '^(?:[A-Za-z]:[\\/]|\.{1,2}[\\/])?(?:[A-Za-z0-9_. -]+[\\/])*\d+\.\d+\.\d+$') {
            return @{state=$tree; classification='path_pointer_candidate'; pointerText=$text}
        }
        return @{state=$tree; classification='unresolved_pointer_format'; contentHash=(Get-Hash $Path); size=$size}
    }
    return @{state=$tree; classification='version_pointer_candidate'; version=$text}
}
function Read-DirectOptional([string]$Path) {
    if (-not (Test-Path -LiteralPath (Split-Path $Path))) {
        return @{kind='absent'; nodes=@(); parentAbsent=$true}
    }
    return Read-Tree $Path
}
function Get-DirectInventory([string]$InstallRoot, [string]$CacheRoot, [string]$DownloadRoot, $Configuration) {
    $uvRoot = Join-Path $InstallRoot 'uv'
    $versions = @()
    $unclassified = @()
    foreach ($item in @(Get-ChildItem -LiteralPath $uvRoot -Force | Sort-Object Name)) {
        if ($item.Name -cmatch '^\d+\.\d+\.\d+$') {
            if (-not $item.PSIsContainer) { throw 'A version slot is not a directory.' }
            $versions += $item.Name
        } elseif ($item.Name -ne '.mise.backend.toml') {
            $unclassified += $item.Name
        }
    }
    $aliases = Get-DirectAliasNames $versions $Configuration
    $slots = @{}
    foreach ($name in $aliases) { $slots[$name] = Get-DirectSlot (Join-Path $uvRoot $name) $versions }
    $versionStates = @{}
    foreach ($name in $versions) { $versionStates[$name] = Read-Tree (Join-Path $uvRoot $name) }
    $legacy = @{}
    foreach ($tool in @(Get-ChildItem -LiteralPath $InstallRoot -Force -Directory | Sort-Object Name)) {
        if ($tool.Name -eq 'uv') { continue }
        # 他ツールのバイナリには入らず、初期化で共有manifestへ移され得る旧metadataだけを読む。
        Assert-Path $tool.FullName
        $legacy[$tool.Name] = Read-Tree (Join-Path $tool.FullName '.mise.backend.toml')
    }
    return @{
        versions=$versionStates; runtimeSlots=$slots
        outsideScopeNames=@($unclassified | Where-Object { $_ -notin $aliases })
        sharedManifest=(Read-Tree (Join-Path $InstallRoot '.mise-installs.toml'))
        uvBackend=(Read-Tree (Join-Path $uvRoot '.mise.backend.toml'))
        otherLegacyMetadata=$legacy
        uvCache=(Read-Tree (Join-Path $CacheRoot 'uv'))
        uvDownloads=(Read-DirectOptional (Join-Path $DownloadRoot 'uv'))
    }
}
function Assert-DirectDestinations([string[]]$Protected, [string]$RecoveryPath, [string]$ReportPath) {
    foreach ($destination in @($RecoveryPath,$ReportPath)) {
        if (Test-Path -LiteralPath $destination) { throw 'Recovery and Report must be new; never reuse an old artifact.' }
        foreach ($path in $Protected) {
            if ($destination -ieq $path -or
                $destination.StartsWith($path.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase) -or
                $path.StartsWith($destination.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase)) {
                throw 'Output/recovery overlaps protected inputs.'
            }
        }
    }
    if ($ReportPath -ieq $RecoveryPath -or
        $ReportPath.StartsWith($RecoveryPath.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase) -or
        $RecoveryPath.StartsWith($ReportPath.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase)) {
        throw 'Report must be separate from the future recovery directory.'
    }
}

function Assert-DirectFreshParent([string]$Path) {
    $parent = Split-Path $Path
    while ($parent) {
        foreach ($name in @('snapshot.json','journal.json','plan.json')) {
            if (Test-Path -LiteralPath (Join-Path $parent $name)) {
                throw 'Do not create new artifacts inside an existing recovery or plan directory.'
            }
        }
        $parent = Split-Path $parent
    }
}

Assert-Native
if (-not $WritersStopped) { throw 'Stop mise/chezmoi/uv and other writers before inventory; -WritersStopped is required.' }
foreach ($name in @('Source','Config','Data','Cache','Recovery','Report')) {
    Set-Variable $name (ConvertTo-DirectPath (Get-Variable $name -ValueOnly))
}
$homeRoot = [Environment]::GetFolderPath('UserProfile')
foreach ($path in @($Source,$Config,$Data,$Cache,$Recovery,$Report)) {
    Assert-Beneath $path $homeRoot
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($path))
    if ($drive.DriveFormat -ne 'NTFS' -or $drive.DriveType -ne 'Fixed' -or
        [IO.Path]::GetPathRoot($path) -ine [IO.Path]::GetPathRoot($Recovery)) {
        throw 'Inputs and future recovery must be on the same fixed NTFS volume.'
    }
}
Assert-DirectDestinations @($Source,(Split-Path $Config),$Data,$Cache) $Recovery $Report
Assert-DirectFreshParent $Recovery
Assert-DirectFreshParent $Report
$userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
foreach ($parent in @((Split-Path $Recovery),(Split-Path $Report)) | Sort-Object -Unique) {
    $acl = Get-Acl -LiteralPath $parent
    foreach ($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq 'Allow' -and
            ([int]$rule.FileSystemRights -band 0x000d0156) -ne 0 -and
            $rule.IdentityReference.Value -notin @($userSid,'S-1-5-18','S-1-5-32-544')) {
            throw 'Report/recovery parent is writable by another principal; no ACL changes are attempted.'
        }
    }
}
Assert-DirectSource $Source $SourceCommit
$chezmoi = (Get-Command chezmoi -CommandType Application -TotalCount 1 -ErrorAction Stop).Source
$mise = (Get-Command mise -CommandType Application -TotalCount 1 -ErrorAction Stop).Source
$sourceTemplate = Join-Path $Source 'home\dot_config\mise\config.toml.tmpl'
$sourceLock = Join-Path $Source 'home\dot_config\mise\private_mise.lock'
$lock = Join-Path (Split-Path $Config) 'mise.lock'
$inputs = @{}
foreach ($path in @($Config,$lock,$sourceTemplate,$sourceLock)) {
    $inputs[$path] = Read-Tree $path
    if ($inputs[$path].kind -ne 'file') { throw 'Input must be an existing regular file.' }
}
$tools=@{}
foreach ($path in @($mise,$chezmoi)) { $tools[$path]=Get-Hash $path }
$original = ConvertFrom-Toml ([IO.File]::ReadAllText($Config)) $chezmoi $Source
$originalLock = ConvertFrom-Toml ([IO.File]::ReadAllText($lock)) $chezmoi $Source
$candidateLock = ConvertFrom-Toml ([IO.File]::ReadAllText($sourceLock)) $chezmoi $Source
$expectedLock = Assert-DirectLock $originalLock $candidateLock $ExpectedVersion
$render = Invoke-Captured $chezmoi @('--config','NUL','--config-format','toml','--source',
    (Join-Path $Source 'home'),'execute-template','--stdinisatty=false','--file',$sourceTemplate) $Source
$rendered = ConvertFrom-Toml $render.stdout $chezmoi $Source
$uvDeclaration = @{version='latest'; platforms=@{'windows-arm64'=@{asset_pattern='uv-x86_64-pc-windows-msvc.zip'}}}
Assert-Equal $rendered.tools.uv $uvDeclaration 'Unexpected source uv declaration.'
Assert-Equal $rendered.tool_alias.uv 'github:astral-sh/uv' 'Unexpected source backend.'
$expectedConfig = Get-DirectCandidateConfig $original $uvDeclaration
$installRoot = Join-Path $Data 'installs'
$inventory = Get-DirectInventory $installRoot $Cache (Join-Path $Data 'downloads') $original
if (-not $inventory.versions.ContainsKey($ExpectedVersion)) { throw 'Requested same-version original directory is missing.' }
foreach ($exe in @('uv.exe','uvx.exe')) {
    $node = @($inventory.versions[$ExpectedVersion].nodes | Where-Object { $_.relative -ceq $exe -and $_.kind -eq 'file' })
    if ($node.Count -ne 1) { throw 'Expected canonical uv/uvx executable is missing; no binary is run by Plan.' }
}
$metadata = @{}
foreach ($path in @((Join-Path $installRoot '.mise-installs.toml'),
        (Join-Path $installRoot 'uv\.mise.backend.toml'))) {
    if (Test-Path -LiteralPath $path) { $metadata[$path] = ConvertFrom-Toml ([IO.File]::ReadAllText($path)) $chezmoi $Source }
}
foreach ($tool in $inventory.otherLegacyMetadata.Keys) {
    if ($inventory.otherLegacyMetadata[$tool].kind -eq 'file') {
        $path = Join-Path $installRoot "$tool\.mise.backend.toml"
        $metadata[$path] = ConvertFrom-Toml ([IO.File]::ReadAllText($path)) $chezmoi $Source
    }
}
$parents = @{}
foreach ($path in @($installRoot,(Join-Path $installRoot 'uv'),$Cache,(Split-Path $Config),
        (Split-Path $Report),(Split-Path $Recovery))) { $parents[$path] = Read-Parent $path }
Assert-Equal (Get-DirectInventory $installRoot $Cache (Join-Path $Data 'downloads') $original) $inventory 'Inventory changed; stop writers and use a new report.'
foreach ($path in $inputs.Keys) { Assert-Equal (Read-Tree $path) $inputs[$path] 'Input changed during Plan.' }
foreach ($path in $tools.Keys) { Assert-Equal (Get-Hash $path) $tools[$path] 'Tool executable changed during Plan.' }
foreach ($path in $parents.Keys) { Assert-Equal (Read-Parent $path) $parents[$path] 'Parent changed during Plan.' }
Assert-DirectSource $Source $SourceCommit
$reportValue = @{
    format='windows-uv-direct-inventory'; schema=1; command='Plan'; canApply=$false
    sourceCommit=$SourceCommit.ToLowerInvariant(); expectedVersion=$ExpectedVersion
    roots=@{config=$Config; data=$Data; cache=$Cache; recovery=$Recovery}
    rootsConfirmedByMise=$false; installedVersionExecuted=$false
    inputs=$inputs; toolHashes=$tools; inventory=$inventory; metadata=$metadata; parents=$parents
    proposedConfigDigest=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes((Get-Json $expectedConfig))))
    proposedLockDigest=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes((Get-Json $expectedLock))))
    blockingDecision='Review runtime pointer formats and other-tool legacy migration from this inventory before implementing direct Install/Restore.'
    installerInvoked=$false; originalsMoved=$false; sacl='unobserved'
}
Write-NewJson $Report $reportValue
@{status='inventory_only_not_installable'; report=$Report; digest=(Get-Hash $Report); canApply=$false} | ConvertTo-Json -Compress
