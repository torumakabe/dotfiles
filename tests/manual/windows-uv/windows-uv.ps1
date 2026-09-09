#requires -Version 7.6
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Prepare','Install','Apply','Restore')][string]$Command,
    [Parameter(Mandatory)][string]$Backup,
    [string]$Config, [string]$Data, [string]$Cache, [string]$Source, [string]$SourceCommit,
    [string]$SnapshotDigest, [string]$PlanDigest,
    [switch]$WritersStopped, [switch]$UseExistingGitHubAuth
)
. (Join-Path $PSScriptRoot 'uv-state.ps1')
Assert-Native
if (-not $WritersStopped) { throw 'Stop mise/chezmoi/editors/uv/background writers first; -WritersStopped is required.' }
Assert-Path $Backup -Absent
$homeRoot = [Environment]::GetFolderPath('UserProfile')
Assert-Beneath $Backup $homeRoot
$drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($Backup))
if ($drive.DriveFormat -ne 'NTFS' -or $drive.DriveType -ne 'Fixed') { throw 'Only a local fixed NTFS volume is supported.' }
$userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$parentAcl = Get-Acl -LiteralPath (Split-Path $Backup)
foreach ($rule in $parentAcl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
    if ($rule.AccessControlType -eq 'Allow' -and
        ([int]$rule.FileSystemRights -band 0x000d0156) -ne 0 -and
        $rule.IdentityReference.Value -notin @($userSid,'S-1-5-18','S-1-5-32-544')) {
        throw 'Backup parent allows another principal to modify files; use an existing private parent.'
    }
}

function New-Directory([string]$Path) { New-ExclusiveDirectory $Path }
function ConvertTo-WindowsPath([string]$Path) {
    $local = $Path.Replace('/','\')
    if ($local -notmatch '^[A-Za-z]:\\') { throw "Unsupported local absolute path: $Path" }
    # 区切りだけを統一し、..、ADS、末尾の空白などはAssert-Pathの拒否対象として残す。
    return [regex]::Replace($local, '\\+', '\')
}
function Assert-MiseEnvironment {
    foreach ($key in @(Get-ChildItem Env: | Where-Object { $_.Name -like 'MISE_*' })) {
        # 公式のPowerShell activationが設定するシェル識別子だけを許可する。
        if ($key.Name -ieq 'MISE_SHELL' -and $key.Value -ceq 'pwsh') { continue }
        throw "Existing $($key.Name) override needs a tailored procedure."
    }
}
function Get-SourceCommit([string]$Source, [string]$SourceCommit) {
    if ($SourceCommit -notmatch '^[0-9a-fA-F]{40}$') { throw 'Prepare requires a full 40-hex SourceCommit.' }
    foreach ($name in @('GIT_DIR','GIT_WORK_TREE','GIT_COMMON_DIR','GIT_INDEX_FILE',
            'GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES')) {
        if (Test-Path "Env:$name") { throw "Existing $name overrides source identity." }
    }
    $git = (Get-Command git -CommandType Application -TotalCount 1 -ErrorAction Stop).Source
    $root = (Invoke-Captured $git @('--no-optional-locks','rev-parse','--show-toplevel') $Source).stdout.Trim()
    if ([IO.Path]::GetFullPath($root).Replace('\','/').TrimEnd('/') -ine
        [IO.Path]::GetFullPath($Source).Replace('\','/').TrimEnd('/')) { throw 'Source must be the Git worktree root, not a subdirectory.' }
    $head = (Invoke-Captured $git @('--no-optional-locks','rev-parse','--verify','HEAD') $Source).stdout.Trim()
    if ($head -ine $SourceCommit) { throw 'Source HEAD does not match SourceCommit.' }
    $status = (Invoke-Captured $git @('--no-optional-locks','status','--porcelain=v1',
        '--untracked-files=all','--ignore-submodules=none') $Source).stdout
    if ($status.Length -ne 0) { throw 'Source has tracked or untracked changes; do not reset, stash or rebaseline.' }
    return $head.ToLowerInvariant()
}
function Get-IsolatedEnvironment($State) {
    @{
        MISE_GLOBAL_CONFIG_FILE = (Join-Path $Backup 'work\config\config.toml')
        MISE_DATA_DIR = (Join-Path $Backup 'work\data')
        MISE_CACHE_DIR = (Join-Path $Backup 'work\cache')
        MISE_STATE_DIR = (Join-Path $Backup 'work\state')
        MISE_NO_HOOKS = '1'; MISE_YES = '1'; MISE_AUTO_INSTALL = '0'
        MISE_TRUSTED_CONFIG_PATHS = (Join-Path $Backup 'work\config\config.toml')
    }
}
function Assert-Originals($State) {
    foreach ($entry in $State.entries) {
        Assert-Equal (Read-Tree $entry.target) $entry.original "Concurrent change: $($entry.target)"
        Assert-Equal (Read-Tree (Join-Path $Backup $entry.saved)) $entry.observation "Damaged observation copy: $($entry.saved)"
    }
    Assert-Parents $State
}
function Assert-Parents($State) {
    foreach ($path in $State.parents.Keys) {
        Assert-Equal (Read-Parent $path) $State.parents[$path] "Parent identity/ACL/attributes changed: $path"
    }
}
function Save-Event([string]$Name, $Value) { Write-NewJson (Join-Path $Backup ($Name + '.json')) $Value }
function Save-Journal($Journal) {
    $stage = Join-Path $Backup ('journal-' + [guid]::NewGuid().ToString('N') + '.json')
    Write-NewJson $stage $Journal
    $destination = Join-Path $Backup 'journal.json'
    $code = Invoke-JournalRename $stage $destination
    if ($code -ne 0) {
        $exception = [ComponentModel.Win32Exception]::new($code,
            "Cannot persist journal replacement (Win32 $code); no further object moves allowed")
        $exception.Data['operation'] = 'MoveFileExW: journal replacement'
        $exception.Data['source'] = $stage
        $exception.Data['destination'] = $destination
        throw $exception
    }
}
function Test-Absent($State) { $State.kind -eq 'absent' }
function Set-CandidateMetadata([string]$Path, $Original) {
    $tree = Read-Tree $Path
    foreach ($node in $tree.nodes) {
        $old = @($Original.nodes | Where-Object { $_.relative -ceq $node.relative -and $_.kind -eq $node.kind })
        if ($old.Count -eq 1) {
            $node.attributes = $old[0].attributes
            # NTFSの同名置換で作成日時が引き継がれるため、候補を封印する前に一致させる。
            if ($node.relative -eq '' -and $node.kind -eq 'file') { $node.created = $old[0].created }
            Set-Node $(if ($node.relative) { Join-Path $Path $node.relative } else { $Path }) $node -KeepDacl
        }
    }
}
function Get-EntryPosition($Entry, $Record, $After) {
    $current = Read-Tree $Entry.target
    if ($null -eq $Record) {
        Assert-Equal $current $Entry.original "Unjournaled target changed: $($Entry.target)"
        return 'untouched'
    }
    $nonce = $Record.nonce
    if ($nonce -notmatch '^[a-f0-9]{32}$' -or
        $Record.originalSource -cne (Join-Path $Backup ('retained-' + $nonce)) -or
        $Record.discard -cne (Join-Path $Backup ('candidate-' + $nonce)) -or
        $Record.stage -cne (Join-Path (Split-Path $Entry.target) ('.n4-uv-stage-' + $nonce)) -or
        $Record.direction -notin @('apply','restore')) { throw 'Invalid retained-object record' }
    Assert-Observed $Record.after $After 'Journal candidate differs from sealed plan'
    $absent = @{kind='absent';nodes=@()}
    $actual = @($current, (Read-Tree $Record.originalSource), (Read-Tree $Record.stage), (Read-Tree $Record.discard))
    # 配列の順序は現在の対象、退避した元オブジェクト、未公開候補、退避した候補。
    $positions = [ordered]@{
        before = @($Entry.original,$absent,$Record.after,$absent)
        evacuated = @($absent,$Entry.original,$Record.after,$absent)
        published = @($Record.after,$Entry.original,$absent,$absent)
    }
    if ($Record.direction -eq 'restore') {
        $positions['candidateEvacuated'] = @($absent,$Entry.original,$absent,$Record.after)
        $positions['restored'] = @($Entry.original,$absent,$absent,$Record.after)
    }
    foreach ($name in $positions.Keys) {
        if ((Get-Json $actual) -ceq (Get-Json $positions[$name])) { return $name }
    }
    throw "Unknown/concurrent object or identity; refusing overwrite: $($Entry.target)"
}
function Get-CurrentStates($State, $Plan, $Journal) {
    $result = @()
    foreach ($key in $Journal.records.Keys) {
        if ($key -notmatch '^(0|[1-9][0-9]*)$' -or [long]$key -ge $State.entries.Count) { throw 'Invalid journal target index' }
    }
    for ($i = 0; $i -lt $State.entries.Count; $i++) {
        $entry = $State.entries[$i]
        $after = if ($null -ne $Plan) { $Plan.entries[$i].after } else { $entry.original }
        $result += Get-EntryPosition $entry $Journal.records["$i"] $after
    }
    return ,$result
}
function Complete-Pending($State, $Journal, [int]$Index) {
    $entry = $State.entries[$Index]
    $record = $Journal.records["$Index"]
    $position = Get-EntryPosition $entry $record $entry.after
    if ($record.direction -eq 'apply') {
        if ($position -eq 'published') { return }
        Assert-Parents $State
        if (-not (Test-Absent (Read-Tree $entry.target))) {
            Move-Tree $entry.target $record.originalSource $entry.original
        }
        Assert-Parents $State
        $null = Get-EntryPosition $entry $record $entry.after
        if (-not (Test-Absent $record.after)) { Move-Tree $record.stage $entry.target $record.after }
        Assert-Equal (Read-Tree $entry.target) $record.after 'Candidate publication verification failed'
    } else {
        if ((Get-Json (Read-Tree $entry.target)) -ceq (Get-Json $entry.original)) { return }
        if (-not (Test-Absent (Read-Tree $entry.target))) {
            Move-Tree $entry.target $record.discard $record.after
        }
        $null = Get-EntryPosition $entry $record $entry.after
        if (-not (Test-Absent $entry.original)) {
            Move-Tree $record.originalSource $entry.target $entry.original
        }
        Assert-Equal (Read-Tree $entry.target) $entry.original 'Original identity/observed metadata restoration failed'
    }
    $null = Get-EntryPosition $entry $record $entry.after
}
function Publish-One($State, $Journal, [int]$Index, [string]$Blob, $Desired, [switch]$Restore) {
    $entry = $State.entries[$Index]
    $record = $Journal.records["$Index"]
    $null = Get-EntryPosition $entry $record $entry.after
    if ($Restore) {
        Assert-Equal $Desired $entry.original 'Restore must select the original object'
        if ($null -eq $record) { return }
        # どちらのrenameよりも先に、選択済みの復元元と復元する意図を保存する。
        if ($record.direction -ne 'restore') {
            $record.direction = 'restore'
            Save-Journal $Journal
        }
    } else {
        Assert-Equal $Desired $entry.after 'Apply must select the sealed candidate'
        Assert-Parents $State
        if ($null -eq $record) {
            if ($entry.original.kind -eq 'file' -and $Desired.kind -eq 'file') {
                Assert-Equal $Desired.nodes[0].created $entry.original.nodes[0].created `
                    'Seal the candidate with original creation time before file replacement'
            }
            if ((Get-Json (Get-ObservedTree $entry.original)) -ceq (Get-Json (Get-ObservedTree $Desired))) { return }
            $nonce = [guid]::NewGuid().ToString('N')
            $stage = Join-Path (Split-Path $entry.target) ('.n4-uv-stage-' + $nonce)
            Copy-Tree $Blob $stage $entry.blobState $Desired
            Assert-Parents $State
            $record = @{ nonce=$nonce; direction='apply'; stage=$stage; after=(Read-Tree $stage)
                originalSource=(Join-Path $Backup ('retained-' + $nonce))
                discard=(Join-Path $Backup ('candidate-' + $nonce)) }
            Assert-Observed $record.after $Desired 'Staged candidate changed'
            $null = Get-EntryPosition $entry $record $entry.after
            $Journal.records["$Index"] = $record
            Save-Journal $Journal
        } elseif ($record.direction -ne 'apply') { throw 'Cannot apply after restore has started' }
    }
    Complete-Pending $State $Journal $Index
}

if ($Command -eq 'Prepare') {
    if (Test-Path -LiteralPath $Backup) { throw 'Backup already exists; never replace or rebaseline it.' }
    Assert-MiseEnvironment
    $Config = ConvertTo-WindowsPath $Config
    $Data = ConvertTo-WindowsPath $Data
    $Cache = ConvertTo-WindowsPath $Cache
    $Source = ConvertTo-WindowsPath $Source
    foreach ($path in @($Config,$Data,$Cache,$Source)) { Assert-Path $path }
    if ($Backup.StartsWith($Source.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase) -or
        $Source.StartsWith($Backup + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Backup must be independent of candidate source.' }
    $verifiedCommit = Get-SourceCommit $Source $SourceCommit
    if ($PSScriptRoot -ine (Join-Path $Source 'tests\manual\windows-uv')) { throw 'Run Prepare from the verified source entry.' }
    $sourceTemplate = Join-Path $Source 'home\dot_config\mise\config.toml.tmpl'
    $sourceLock = Join-Path $Source 'home\dot_config\mise\private_mise.lock'
    foreach ($file in @($sourceTemplate,$sourceLock,(Join-Path $PSScriptRoot 'windows-uv.ps1'),
            (Join-Path $PSScriptRoot 'uv-state.ps1'))) {
        Assert-Path $file
    }
    foreach ($path in @($Config,$Data,$Cache)) {
        Assert-Beneath $path $homeRoot
        if ([IO.Path]::GetPathRoot($path) -ine [IO.Path]::GetPathRoot($Backup)) { throw 'All managed paths and backup must be on the same NTFS volume.' }
        if ($Backup.StartsWith($path.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase) -or
            $path.StartsWith($Backup + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Backup overlaps managed paths.' }
    }
    if ([IO.Path]::GetFileName($Config) -cne 'config.toml') { throw 'Expected config.toml' }
    $targets = @(Get-Targets $Config $Data $Cache)
    for ($i=0; $i -lt $targets.Count; $i++) {
        Assert-Path $targets[$i] -Absent
        for ($j=0; $j -lt $i; $j++) {
            if ($targets[$i] -ieq $targets[$j] -or $targets[$i].StartsWith($targets[$j] + '\',[StringComparison]::OrdinalIgnoreCase) -or
                $targets[$j].StartsWith($targets[$i] + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Overlapping targets' }
        }
    }
    $mise = (Get-Command mise -CommandType Application -TotalCount 1 -ErrorAction Stop).Source
    $chezmoi = (Get-Command chezmoi -CommandType Application -TotalCount 1 -ErrorAction Stop).Source
    New-Directory $Backup
    New-Directory (Join-Path $Backup 'observations')
    New-Directory (Join-Path $Backup 'work')
    New-Directory (Join-Path $Backup 'work\config')
    New-Directory (Join-Path $Backup 'work\data')
    New-Directory (Join-Path $Backup 'work\data\installs')
    New-Directory (Join-Path $Backup 'work\data\installs\uv')
    New-Directory (Join-Path $Backup 'work\data\downloads')
    New-Directory (Join-Path $Backup 'work\data\shims')
    New-Directory (Join-Path $Backup 'work\cache')
    New-Directory (Join-Path $Backup 'work\state')
    foreach ($file in @('windows-uv.ps1','uv-state.ps1')) {
        [IO.File]::Copy((Join-Path $PSScriptRoot $file),(Join-Path $Backup $file),$false)
    }
    $entries = @()
    $parents = @{}
    foreach ($path in @($targets | ForEach-Object { Split-Path $_ }) +
        @($Backup,(Join-Path $Backup 'observations'))) {
        $parents[$path] = Read-Parent $path
    }
    for ($i=0; $i -lt $targets.Count; $i++) {
        $original = Read-Tree $targets[$i]
        $saved = "observations\$i"
        Copy-Tree $targets[$i] (Join-Path $Backup $saved) $original
        $entries += @{ target=$targets[$i]; saved=$saved; original=$original
            observation=(Read-Tree (Join-Path $Backup $saved)) }
    }
    foreach ($i in @(0,1,3)) { if ($entries[$i].original.kind -ne 'file') { throw 'Config, lock and shared install manifest must exist as regular files.' } }
    if ($entries[2].original.kind -ne 'directory') { throw 'Old uv install must be a directory.' }
    if (-not (Test-Path -LiteralPath (Join-Path $Data 'installs\uv\0.12.10\uv.exe'))) { throw 'Expected uv 0.12.10 Windows executable.' }
    $work = Join-Path $Backup 'work'
    $queryEnv=@{ MISE_NO_HOOKS='1'; MISE_AUTO_INSTALL='0'
        MISE_STATE_DIR=(Join-Path $work 'state'); MISE_CACHE_DIR=(Join-Path $work 'cache') }
    $activeConfigs=(Invoke-Captured $mise @('config','ls','--json') $work $queryEnv).stdout | ConvertFrom-Json
    Assert-Equal @($activeConfigs | ForEach-Object { ConvertTo-WindowsPath $_.path }) @($Config) 'Input is not the sole active global config'
    $where=ConvertTo-WindowsPath (Invoke-Captured $mise @('where','uv') $work $queryEnv).stdout.Trim()
    if ($where -ine (Join-Path $Data 'installs\uv\0.12.10')) { throw 'Input data directory does not match installed uv.' }
    $cacheQuery=@{MISE_NO_HOOKS='1';MISE_AUTO_INSTALL='0';MISE_STATE_DIR=(Join-Path $work 'state')}
    $activeCache=ConvertTo-WindowsPath (Invoke-Captured $mise @('cache','path') $work $cacheQuery).stdout.Trim()
    if ($activeCache -ine $Cache) { throw 'Input cache directory does not match mise cache path.' }
    $state = @{ schema=3; sacl='unobserved'; rollback='same_volume_original_object'
        sourceCommit=$verifiedCommit
        config=$Config; data=$Data; cache=$Cache; home=$homeRoot
        entries=$entries; parents=$parents; mise=$mise; miseHash=(Get-Hash $mise); chezmoi=$chezmoi
        scripts=@{}; sandboxSuccess=$false }
    $state.miseVersion=(Invoke-Captured $mise @('--version') $work $queryEnv).stdout.Trim()
    foreach ($file in @('windows-uv.ps1','uv-state.ps1')) { $state.scripts[$file] = Get-Hash (Join-Path $Backup $file) }
    $oldConfig = ConvertFrom-Toml ([IO.File]::ReadAllText($Config)) $chezmoi $work
    $oldLock = ConvertFrom-Toml ([IO.File]::ReadAllText($targets[1])) $chezmoi $work
    if ($oldConfig.tools.Count -ne 31 -or $oldLock.tools.Count -ne 31) { throw 'Expected exactly 31 tool declarations/locks.' }
    if ($oldConfig.tools.uv -cne 'latest') { throw 'Custom uv options are unsupported.' }
    if ($oldConfig.ContainsKey('tool_alias') -and $oldConfig.tool_alias.ContainsKey('uv') -and
        $oldConfig.tool_alias.uv -cne 'aqua:astral-sh/uv') { throw 'Expected original aqua uv alias.' }
    foreach ($entry in $oldLock.tools.uv) {
        if ($entry.version -cne '0.12.10' -or $entry.backend -cne 'aqua:astral-sh/uv') { throw 'Expected only aqua uv 0.12.10 locks.' }
    }
    $render = Invoke-Captured $chezmoi @('--config','NUL','--config-format','toml','--source',
        (Join-Path $Source 'home'),'execute-template','--stdinisatty=false','--file',$sourceTemplate) $work
    if ($render.stdout.Contains('CANDIDATE_USER')) { throw 'Placeholder render is not deployable.' }
    $rendered = ConvertFrom-Toml $render.stdout $chezmoi $work
    $candidateLock = ConvertFrom-Toml ([IO.File]::ReadAllText($sourceLock)) $chezmoi $work
    $expectedUv = @{ version='latest'; platforms=@{ 'windows-arm64'=@{asset_pattern='uv-x86_64-pc-windows-msvc.zip'} } }
    Assert-Equal $rendered.tools.uv $expectedUv 'Unexpected rendered uv declaration'
    if ($rendered.tool_alias.uv -cne 'github:astral-sh/uv' -or $candidateLock.tools.uv.Count -ne 2) { throw 'Expected GitHub backend and two options-distinct uv lock entries.' }
    $armEntries=@($candidateLock.tools.uv | Where-Object { $_.ContainsKey('platforms.windows-arm64') })
    if ($armEntries.Count -ne 1) { throw 'Missing/ambiguous Windows ARM64 entry.' }
    Assert-Equal $armEntries[0].options @{asset_pattern='uv-x86_64-pc-windows-msvc.zip'} 'ARM64 must retain x64 asset override'
    $platforms=@($candidateLock.tools.uv | ForEach-Object { $_.Keys } | Where-Object { $_ -like 'platforms.*' } | Sort-Object)
    Assert-Equal $platforms @('platforms.linux-arm64','platforms.linux-x64','platforms.macos-arm64','platforms.windows-arm64','platforms.windows-x64') 'Unexpected platform set'
    foreach ($entry in $candidateLock.tools.uv) {
        if ($entry.backend -cne 'github:astral-sh/uv' -or $entry.version -cne '0.12.10') { throw 'Unexpected candidate uv lock.' }
        foreach ($platform in @($entry.Keys | Where-Object { $_ -like 'platforms.*' })) {
            $previous = @($oldLock.tools.uv | Where-Object { $_.ContainsKey($platform) })
            if ($previous.Count -ne 1) { throw "Ambiguous original asset: $platform" }
            foreach ($field in @('url','checksum','provenance')) {
                Assert-Equal $entry[$platform][$field] $previous[0][$platform][$field] "Asset changed: $platform/$field"
            }
        }
    }
    $stagedTargets = @(Get-Targets (Join-Path $work 'config\config.toml') (Join-Path $work 'data') (Join-Path $work 'cache'))
    foreach ($path in @($stagedTargets | ForEach-Object { Split-Path $_ })) {
        $state.parents[$path] = Read-Parent $path
    }
    for ($i=0; $i -lt $targets.Count; $i++) {
        $copySource = Join-Path $Backup $entries[$i].saved
        Copy-Tree $copySource $stagedTargets[$i] $entries[$i].observation
    }
    $envMap = Get-IsolatedEnvironment $state
    $oldTool = (Invoke-Captured $mise @('tool','uv','--json') $work $envMap).stdout | ConvertFrom-Json
    if ($oldTool.backend -cne 'aqua:astral-sh/uv') { throw 'Expected original aqua backend.' }
    Assert-Equal @($oldTool.active_versions) @('0.12.10') 'Expected existing version 0.12.10'
    # Only these three uv keys are changed; the remaining 30 declarations/settings survive.
    foreach ($pair in @(
        @('tools.uv.version','latest'),
        @('tools.uv.platforms.windows-arm64.asset_pattern','uv-x86_64-pc-windows-msvc.zip'),
        @('tool_alias.uv','github:astral-sh/uv'))) {
        $null = Invoke-Captured $mise @('config','set','--file',$stagedTargets[0],$pair[0],$pair[1]) $work $envMap
    }
    $expectedConfig = (Get-Json $oldConfig) | ConvertFrom-Json -AsHashtable
    $expectedConfig.tools.uv = $expectedUv
    if (-not $expectedConfig.ContainsKey('tool_alias')) { $expectedConfig.tool_alias=@{} }
    $expectedConfig.tool_alias.uv='github:astral-sh/uv'
    Assert-Equal (ConvertFrom-Toml ([IO.File]::ReadAllText($stagedTargets[0])) $chezmoi $work) $expectedConfig 'Non-uv config change'
    $uvBlocks = @([regex]::Split([IO.File]::ReadAllText($sourceLock),'(?m)(?=^\[\[tools\.)') |
        Where-Object { $_.StartsWith('[[tools.uv]]') })
    if ($uvBlocks.Count -ne 2) { throw 'Unsupported candidate lock layout' }
    $replaced = $false
    $blocks = foreach ($block in [regex]::Split([IO.File]::ReadAllText($targets[1]),'(?m)(?=^\[\[tools\.)')) {
        if ($block.StartsWith('[[tools.uv]]')) {
            if (-not $replaced) { $uvBlocks -join ''; $replaced=$true }
        } else { $block }
    }
    if (-not $replaced) { throw 'No old uv block' }
    [IO.File]::WriteAllText($stagedTargets[1],($blocks -join ''))
    $expectedLock = (Get-Json $oldLock) | ConvertFrom-Json -AsHashtable
    $expectedLock.tools.uv=$candidateLock.tools.uv
    Assert-Equal (ConvertFrom-Toml ([IO.File]::ReadAllText($stagedTargets[1])) $chezmoi $work) $expectedLock 'Non-uv lock change'
    $state.candidateHashes=@((Get-Hash $stagedTargets[0]),(Get-Hash $stagedTargets[1]))
    $state.otherMetadata = Get-WithoutUv (ConvertFrom-Toml ([IO.File]::ReadAllText($targets[3])) $chezmoi $work)
    for ($i=0; $i -lt $targets.Count; $i++) {
        $tree = Read-Tree $stagedTargets[$i]
        $requirements = Get-CopyRequirements $tree $state.parents[(Split-Path $stagedTargets[$i])] $entries[$i].original
        Assert-Observed $tree $requirements 'Prepared work ACL/owner/group differs from private copy policy'
        $entries[$i].work = $tree
    }
    Assert-Originals $state
    Assert-Path $Source
    $null = Get-SourceCommit $Source $verifiedCommit
    Write-NewJson (Join-Path $Backup 'snapshot.json') $state
    Write-NewJson (Join-Path $Backup 'journal.json') @{ phase='prepared'; records=@{} }
    @{ status='prepared_not_installed'; snapshotDigest=(Get-Hash (Join-Path $Backup 'snapshot.json')); backup=$Backup } | ConvertTo-Json
    exit 0
}

if (-not $SnapshotDigest -or (Get-Hash (Join-Path $Backup 'snapshot.json')) -cne $SnapshotDigest) { throw 'Snapshot digest mismatch; supply the separately recorded digest.' }
$state = Read-Json (Join-Path $Backup 'snapshot.json')
if ($state.schema -ne 3) { throw 'Unsupported snapshot schema; use the matching saved scripts for a complete older backup. Never upgrade or rebaseline it.' }
if ($state.home -ine $homeRoot) { throw 'Different target user.' }
foreach ($file in $state.scripts.Keys) {
    if ((Get-Hash (Join-Path $Backup $file)) -cne $state.scripts[$file]) { throw 'Saved recovery script changed.' }
}
if ($Command -in @('Install','Apply')) { Assert-MiseEnvironment }
$lease = [IO.FileStream]::new((Join-Path $Backup 'operation.lock'),'OpenOrCreate','ReadWrite','None')
try {
    $journal = Read-Json (Join-Path $Backup 'journal.json')
    if ($journal.phase -notin @('prepared','install-started','installed','applying','applied','restoring','restored')) {
        throw 'Unknown journal phase; do not rebaseline.'
    }
    $work = Join-Path $Backup 'work'
    $stagedTargets = @(Get-Targets (Join-Path $work 'config\config.toml') (Join-Path $work 'data') (Join-Path $work 'cache'))
    $envMap = Get-IsolatedEnvironment $state
    if ($Command -eq 'Install') {
        if ($journal.phase -ne 'prepared') { throw 'Install is one-shot; preserve failed work and restore, do not retry force install.' }
        Assert-Originals $state
        for ($i=0; $i -lt $state.entries.Count; $i++) {
            Assert-Equal (Read-Tree $stagedTargets[$i]) $state.entries[$i].work 'Prepared private work changed'
        }
        if ((Get-Hash $state.mise) -cne $state.miseHash) { throw 'mise executable changed.' }
        Assert-Equal @((Get-Hash $stagedTargets[0]),(Get-Hash $stagedTargets[1])) $state.candidateHashes 'Prepared config/lock changed'
        $configs = (Invoke-Captured $state.mise @('config','ls','--json') $work $envMap).stdout | ConvertFrom-Json
        Assert-Equal @($configs | ForEach-Object { ConvertTo-WindowsPath $_.path }) @($stagedTargets[0]) 'Unexpected additional mise config'
        if ($UseExistingGitHubAuth) {
            $token = if ($env:GH_TOKEN) { $env:GH_TOKEN } elseif ($env:GITHUB_TOKEN) { $env:GITHUB_TOKEN }
                else { (Invoke-Captured (Get-Command gh -CommandType Application -TotalCount 1 -ErrorAction Stop).Source @('auth','token','--hostname','github.com') $work).stdout.Trim() }
            if (-not $token) { throw 'Existing GitHub authentication unavailable; no login attempted.' }
            $envMap.GITHUB_TOKEN=$token
        }
        $journal.phase='install-started'; Save-Journal $journal
        try {
            $result = Invoke-Captured $state.mise @('--locked','install','--force','uv') $work $envMap -AllowFailure
        } finally { $null=$envMap.Remove('GITHUB_TOKEN'); $token=$null }
        Save-Event 'install-status' @{ exitCode=$result.exitCode; output='withheld_to_avoid_secrets'; isolated=$true; sandboxSuccess=$false }
        Assert-Originals $state
        if ($result.exitCode -ne 0) { throw 'Isolated install failed. Live originals remain intact; use Restore. Do not retry.' }
        Assert-Equal @((Get-Hash $stagedTargets[0]),(Get-Hash $stagedTargets[1])) $state.candidateHashes 'Install changed locked config/lock'
        $meta = ConvertFrom-Toml ([IO.File]::ReadAllText($stagedTargets[3])) $state.chezmoi $work
        Assert-Equal (Get-WithoutUv $meta) $state.otherMetadata 'Install changed metadata for other tools'
        $tool = (Invoke-Captured $state.mise @('tool','uv','--json') $work $envMap).stdout | ConvertFrom-Json
        if ($tool.backend -cne 'github:astral-sh/uv') { throw 'Backend did not migrate.' }
        $resolutions = @()
        foreach ($name in @('uv','uvx')) {
            $exe = ConvertTo-WindowsPath (Invoke-Captured $state.mise @('which',$name) $work $envMap).stdout.Trim()
            $expected = Join-Path $work "data\installs\uv\0.12.10\$name.exe"
            if ($exe -ine $expected) { throw "Unexpected $name resolution." }
            $pe=[IO.File]::ReadAllBytes($exe)
            if ($pe.Length -lt 64) { throw 'Invalid PE executable.' }
            $offset=[BitConverter]::ToInt32($pe,60)
            if ($offset -lt 0 -or $offset -gt $pe.Length-6 -or
                [BitConverter]::ToUInt32($pe,$offset) -ne 0x4550 -or
                [BitConverter]::ToUInt16($pe,$offset+4) -ne 0x8664) { throw 'Expected x64 PE on Windows x64 and ARM64.' }
            $version = (Invoke-Captured $exe @('--version') $work $envMap).stdout.Trim()
            if ($version -notmatch "^$name 0\.12\.10(\s|$)") { throw 'Version mismatch.' }
            $resolutions += @{ name=$name; executable=$exe; version=$version }
        }
        $planEntries=@()
        for ($i=0; $i -lt $state.entries.Count; $i++) {
            $tree=Read-Tree $stagedTargets[$i]
            $privateRequirements=Get-CopyRequirements $tree $state.parents[(Split-Path $stagedTargets[$i])] $state.entries[$i].work
            Assert-Observed $tree $privateRequirements 'Installer changed private ACL/owner/group policy'
            Set-CandidateMetadata $stagedTargets[$i] $state.entries[$i].original
            $tree=Read-Tree $stagedTargets[$i]
            foreach ($node in $tree.nodes | Where-Object { $_.kind -eq 'file' }) {
                $file=if ($node.relative) { Join-Path $stagedTargets[$i] $node.relative } else { $stagedTargets[$i] }
                $bytes=[IO.File]::ReadAllBytes($file)
                foreach ($encoding in @([Text.Encoding]::UTF8,[Text.Encoding]::Unicode)) {
                    $text=$encoding.GetString($bytes)
                    if ($text.Contains($Backup,[StringComparison]::OrdinalIgnoreCase) -or
                        $text.Contains($Backup.Replace('\','/'),[StringComparison]::OrdinalIgnoreCase)) {
                        throw "Generated output embeds isolated path: $file"
                    }
                }
            }
            $after=Get-CopyRequirements $tree $state.parents[(Split-Path $state.entries[$i].target)] $state.entries[$i].original -Publication
            $planEntries+=@{ blob=$stagedTargets[$i]; blobState=$tree; after=$after }
        }
        Assert-Originals $state
        Write-NewJson (Join-Path $Backup 'plan.json') @{ schema=3; entries=$planEntries; resolutions=$resolutions }
        $journal.phase='installed'; Save-Journal $journal
        @{ status='isolated_install_verified_not_applied'; planDigest=(Get-Hash (Join-Path $Backup 'plan.json')); sandboxSuccess=$false } | ConvertTo-Json
        exit 0
    }
    $plan=$null
    if (Test-Path -LiteralPath (Join-Path $Backup 'plan.json')) {
        if (-not $PlanDigest -or (Get-Hash (Join-Path $Backup 'plan.json')) -cne $PlanDigest) { throw 'Plan digest required/mismatch.' }
        $plan=Read-Json (Join-Path $Backup 'plan.json')
        if ($plan.schema -ne 3 -or $plan.entries.Count -ne $state.entries.Count) { throw 'Unsupported or incomplete plan' }
    }
    if ($Command -eq 'Apply' -and ($null -eq $plan -or $journal.phase -notin @('installed','applying','applied'))) { throw 'No completed install plan, or backup already restored.' }
    for ($i=0; $i -lt $state.entries.Count; $i++) {
        $state.entries[$i].after=if ($null -ne $plan) { $plan.entries[$i].after } else { $state.entries[$i].original }
        if ($null -ne $plan) {
            $entry=$plan.entries[$i]
            Assert-Equal $entry.blob $stagedTargets[$i] 'Unexpected candidate blob path'
            $requirements=Get-CopyRequirements $entry.blobState $state.parents[(Split-Path $state.entries[$i].target)] $state.entries[$i].original -Publication
            Assert-Equal $entry.after $requirements 'Publication requirements differ from sealed original/parent policy'
            $state.entries[$i].blobState=$entry.blobState
        }
    }
    if ($Command -eq 'Apply') {
        Assert-Parents $state
        foreach ($entry in $state.entries) {
            Assert-Equal (Read-Tree (Join-Path $Backup $entry.saved)) $entry.observation 'Damaged observation copy'
        }
        foreach ($entry in $plan.entries) { Assert-Equal (Read-Tree $entry.blob) $entry.blobState 'Prepared output changed' }
    }
    $null=Get-CurrentStates $state $plan $journal
    $alreadyRestored=$Command -eq 'Restore' -and $journal.phase -eq 'restored'
    if (-not $alreadyRestored) {
        $journal.phase=if ($Command -eq 'Apply') { 'applying' } else { 'restoring' }
        Save-Journal $journal
        for ($i=0; $i -lt $state.entries.Count; $i++) {
            if ($Command -eq 'Apply') { Assert-Parents $state }
            $null=Get-CurrentStates $state $plan $journal
            $blob=if ($Command -eq 'Apply') { $plan.entries[$i].blob } else { '' }
            $desired=if ($Command -eq 'Apply') { $plan.entries[$i].after } else { $state.entries[$i].original }
            Publish-One $state $journal $i $blob $desired -Restore:($Command -eq 'Restore')
        }
    }
    if ($Command -eq 'Restore') {
        foreach ($entry in $state.entries) {
            Assert-Equal (Read-Tree $entry.target) $entry.original 'Restored original identity/observed metadata mismatch'
        }
    }
    if (-not $alreadyRestored) {
        $journal.phase=if ($Command -eq 'Apply') { 'applied' } else { 'restored' }
        Save-Journal $journal
    }
    if ($Command -eq 'Apply') {
        $observations=@()
        $liveEnv=@{MISE_NO_HOOKS='1'; MISE_AUTO_INSTALL='0'; MISE_STATE_DIR=(Join-Path $work 'state'); MISE_CACHE_DIR=(Join-Path $work 'cache')}
        foreach ($name in @('uv','uvx')) {
            $exe=(Invoke-Captured $state.mise @('which',$name) $work $liveEnv).stdout.Trim()
            if ($exe -ine (Join-Path $state.data "installs\uv\0.12.10\$name.exe")) { throw 'Live resolution mismatch.' }
            $version=(Invoke-Captured $exe @('--version') $work).stdout.Trim()
            if ($version -notmatch "^$name 0\.12\.10(\s|$)") { throw 'Live version mismatch.' }
            $observations+=@{name=$name; executable=$exe; version=$version}
        }
        $log=Join-Path $Backup ('live-resolution-' + [guid]::NewGuid().ToString('N') + '.json')
        Write-NewJson $log @{ observations=$observations; sandboxSuccess=$false }
    }
    @{status=$journal.phase; backup=$Backup; sandboxSuccess=$false} | ConvertTo-Json
} finally { $lease.Dispose() }
