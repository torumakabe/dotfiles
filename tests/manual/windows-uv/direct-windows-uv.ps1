#requires -Version 7.6
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Prepare','Install','Restore')][string]$Command,
    [Parameter(Mandatory)][string]$Recovery,
    [string]$RecoveryDigest,
    [string]$Report, [string]$ReportDigest,
    [string]$Source, [string]$SourceCommit,
    [switch]$WritersStopped,
    [switch]$QuarantineInterruptedOutputs
)
$Command = switch ($Command) { 'Prepare' {'Prepare'} 'Install' {'Install'} 'Restore' {'Restore'} }
if ($QuarantineInterruptedOutputs -and $Command -cne 'Restore') {
    throw 'QuarantineInterruptedOutputs is only valid for an explicit offline Restore.'
}

# RestoreはGit、mise、元checkoutを使わず、外部から渡したdigestで保存コードを検証する。
if ($Command -ne 'Prepare') {
    if ($RecoveryDigest -notmatch '^[0-9A-Fa-f]{64}$') { throw 'RecoveryDigest is required.' }
    $snapshotPath = Join-Path $Recovery 'direct-snapshot.json'
    $snapshotBytes=[IO.File]::ReadAllBytes($snapshotPath)
    if ([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($snapshotBytes)) -ine $RecoveryDigest) {
        throw 'Recovery digest mismatch.'
    }
    $bootstrap = [Text.Encoding]::UTF8.GetString($snapshotBytes) | ConvertFrom-Json -AsHashtable
    if ($bootstrap.format -cne 'windows-uv-direct-recovery' -or $bootstrap.schema -ne 1) {
        throw 'Not an independent direct recovery.'
    }
    foreach ($name in @('direct-windows-uv.ps1','plan-direct-windows-uv.ps1','uv-state.ps1')) {
        foreach ($root in @($Recovery,$PSScriptRoot)) {
            if ((Get-FileHash -LiteralPath (Join-Path $root $name) -Algorithm SHA256).Hash -ine $bootstrap.scripts[$name]) {
                throw 'Pinned recovery script hash mismatch.'
            }
        }
    }
}
. (Join-Path $PSScriptRoot 'uv-state.ps1')
# 既存Planの読取専用関数を共有する。Planのトップレベル処理は実行しない。
$tokens=$null; $parseErrors=$null
$planAst = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot 'plan-direct-windows-uv.ps1'),[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) { throw 'Pinned Plan parser error.' }
foreach ($function in $planAst.FindAll({
    param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]
},$false)) { . ([scriptblock]::Create($function.Extent.Text)) }

function Write-DirectBytes([string]$Path, [byte[]]$Bytes) {
    $stream = [IO.FileStream]::new($Path,'CreateNew','Write','None')
    try { $stream.Write($Bytes); $stream.Flush($true) } finally { $stream.Dispose() }
}
function Get-DirectDigest($Value) {
    [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes((Get-Json $Value))))
}
function Assert-DirectHash([string]$Path, [string]$Digest) {
    if ($Digest -notmatch '^[0-9a-fA-F]{64}$' -or (Get-Hash $Path) -ine $Digest) { throw 'Input hash mismatch.' }
}
function ConvertTo-DirectToml($Value, [string]$Chezmoi, [string]$Work) {
    $expression = '{{ ' + (ConvertTo-Json -InputObject (Get-Json $Value) -Compress) + ' | fromJson | toToml }}'
    (Invoke-Captured $Chezmoi @('--config','NUL','--config-format','toml','--source',$Work,
        'execute-template','--stdinisatty=false') $Work @{} $expression).stdout
}
function Get-DirectScripts([string]$Root) {
    $hashes=@{}
    foreach ($name in @('direct-windows-uv.ps1','plan-direct-windows-uv.ps1','uv-state.ps1')) {
        $hashes[$name]=Get-Hash (Join-Path $Root $name)
    }
    return $hashes
}
function Assert-DirectSourceInputs([string]$Root, $Inputs) {
    # 新実装のSHAは元Reportと異なってよい。設定入力は元Reportの明示的ハッシュも満たす。
    foreach ($relative in @('home\dot_config\mise\config.toml.tmpl','home\dot_config\mise\private_mise.lock')) {
        $old=@($Inputs.Keys | Where-Object { $_.EndsWith('\'+$relative,[StringComparison]::OrdinalIgnoreCase) })
        if ($old.Count -ne 1) { throw 'Missing original source-input seal.' }
        if ((Read-Tree (Join-Path $Root $relative)).kind -ne 'file') { throw 'Source input is not an ordinary file.' }
        Assert-DirectHash (Join-Path $Root $relative) $Inputs[$old[0]].nodes[0].hash
    }
}
function Assert-DirectPrivateParent([string]$Path) {
    $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    foreach ($rule in (Get-Acl -LiteralPath $Path).GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq 'Allow' -and ([int]$rule.FileSystemRights -band 0x000d0156) -ne 0 -and
            $rule.IdentityReference.Value -notin @($sid,'S-1-5-18','S-1-5-32-544')) {
            throw 'Recovery parent is writable by another principal; ACLs will not be changed.'
        }
    }
}
function Assert-DirectFreshRecoveryParent([string]$Path) {
    Assert-DirectFreshParent $Path
    $parent=Split-Path $Path
    while ($parent) {
        if (Test-Path -LiteralPath (Join-Path $parent 'direct-snapshot.json')) {
            throw 'Do not nest a migration inside an existing direct recovery.'
        }
        $parent=Split-Path $parent
    }
}
function Assert-DirectManifestEntry($Entry, [switch]$ToolToml) {
    $keys=@($Entry.Keys | Where-Object { $_ -cne 'opts' } | Sort-Object)
    Assert-Equal $keys @('explicit_backend','full','short') 'Unsupported manifest fields.'
    if ($Entry.ContainsKey('opts') -and ($ToolToml -or $Entry.opts -isnot [Collections.IDictionary])) {
        throw 'Unsupported manifest options.'
    }
    if ($Entry.short -isnot [string] -or $Entry.full -isnot [string] -or
        $Entry.explicit_backend -isnot [bool] -or $Entry.full.Contains('[') -or
        $Entry.short -notmatch '^[A-Za-z0-9_:/.-]+$') { throw 'Unsupported manifest meaning.' }
}
function Assert-DirectMetadata($Metadata, $Inventory, [string]$Installs) {
    $shared=$Metadata[(Join-Path $Installs '.mise-installs.toml')]
    if ($shared.Count -ne 41 -or -not $shared.ContainsKey('uv')) { throw 'Unexpected shared manifest contract.' }
    foreach ($key in $shared.Keys) {
        Assert-DirectManifestEntry $shared[$key]
    }
    $present=0
    foreach ($tool in $Inventory.otherLegacyMetadata.Keys) {
        $tree=$Inventory.otherLegacyMetadata[$tool]
        if ($tree.kind -eq 'absent') {
            if (-not $shared.ContainsKey($tool)) { throw 'Missing shared metadata could trigger legacy fallback.' }
            continue
        }
        if ($tree.kind -ne 'file' -or -not $shared.ContainsKey($tool)) { throw 'Unexpected legacy metadata contract.' }
        $present++
        # 上流は個別TOMLを優先する。共有側との差を統合せず、それぞれの意味を保持する。
        Assert-DirectManifestEntry $Metadata[(Join-Path $Installs "$tool\.mise.backend.toml")] -ToolToml
    }
    if ($present -ne 27) { throw 'Expected the observed 27 other TOML metadata files.' }
    $uv=$Metadata[(Join-Path $Installs 'uv\.mise.backend.toml')]
    Assert-DirectManifestEntry $uv -ToolToml
    if ($uv.short -cne 'uv' -or $uv.full -cne 'aqua:astral-sh/uv') { throw 'Original uv backend is not aqua.' }
}
function Assert-DirectPointers($Inventory) {
    Assert-Equal @($Inventory.runtimeSlots.Keys | Sort-Object) @('0','0.11','0.12','latest') 'Unexpected runtime slots.'
    foreach ($name in $Inventory.runtimeSlots.Keys) {
        $slot=$Inventory.runtimeSlots[$name]
        $version=if ($name -ceq '0.11') { '0.11.31' } else { '0.12.10' }
        if ($slot.classification -cne 'path_pointer_candidate' -or $slot.state.kind -cne 'file' -or
            $slot.pointerText -cne ".\$version") { throw 'Runtime pointer differs from the observed Windows contract.' }
    }
    Assert-Equal @($Inventory.versions.Keys | Sort-Object) @(
        '0.11.29','0.11.31','0.12.0','0.12.10','0.12.2','0.12.5','0.12.7','0.12.8','0.12.9') 'Unexpected original version set.'
}
function Get-DirectEnvironment($State) {
    $work=Join-Path $State.recovery 'work'
    @{
        MISE_GLOBAL_CONFIG_FILE=(Join-Path $work 'config\config.toml')
        MISE_CONFIG_DIR=(Join-Path $work 'config'); MISE_GLOBAL_CONFIG_ROOT=$work
        MISE_CEILING_PATHS=$work; MISE_SYSTEM_CONFIG_DIR=(Join-Path $work 'system')
        MISE_SYSTEM_CONFIG_FILE=(Join-Path $work 'system\config.toml')
        MISE_DATA_DIR=$State.roots.data; MISE_INSTALLS_DIR=(Join-Path $State.roots.data 'installs')
        MISE_DOWNLOADS_DIR=(Join-Path $State.roots.data 'downloads')
        MISE_CACHE_DIR=(Join-Path $work 'cache'); MISE_STATE_DIR=(Join-Path $work 'state')
        MISE_SHIMS_DIR=(Join-Path $work 'shims'); MISE_PLUGINS_DIR=(Join-Path $work 'plugins')
        MISE_SYSTEM_DATA_DIR=(Join-Path $work 'system'); MISE_SHARED_INSTALL_DIRS=''
        MISE_TMP_DIR=(Join-Path $work 'temp'); MISE_NO_HOOKS='1'; MISE_YES='1'
        MISE_AUTO_INSTALL='0'; MISE_ENABLE_TOOLS='uv'; MISE_NO_ENV='1'; MISE_SHELL='pwsh'
        MISE_TRUSTED_CONFIG_PATHS=(Join-Path $work 'config\config.toml')
    }
}
function Get-DirectGitHubToken([string]$Work) {
    $token = if ($env:GH_TOKEN) { $env:GH_TOKEN } elseif ($env:GITHUB_TOKEN) { $env:GITHUB_TOKEN }
        else {
            $gh=(Get-Command gh -CommandType Application -TotalCount 1 -ErrorAction Stop).Source
            (Invoke-Captured $gh @('auth','token','--hostname','github.com') $Work).stdout.Trim()
        }
    if ([string]::IsNullOrWhiteSpace($token)) { throw 'Existing GitHub authentication unavailable; no login attempted.' }
    return $token
}
function Assert-DirectGitHubAccess([string]$Token, [string]$Digest) {
    if ($Digest -cnotmatch '^sha256:[0-9a-f]{64}$') { throw 'Invalid pinned attestation digest.' }
    $headers=@{Authorization="Bearer $Token";Accept='application/vnd.github+json';'X-GitHub-Api-Version'='2022-11-28'}
    try {
        $response=Invoke-WebRequest -Uri "https://api.github.com/repos/astral-sh/uv/attestations/$Digest" `
            -Method Get -Headers $headers -UserAgent 'dotfiles-uv-migration' -SkipHttpErrorCheck `
            -MaximumRedirection 0 -TimeoutSec 30
        if ($response.StatusCode -ne 200) {
            throw "GitHub attestation preflight failed (HTTP $($response.StatusCode)). Originals have not been moved. $($response.Content)"
        }
        $body=$response.Content | ConvertFrom-Json -AsHashtable
        if (-not $body.ContainsKey('attestations') -or @($body.attestations).Count -eq 0) {
            throw 'GitHub attestation preflight returned no attestations for the pinned asset. Originals have not been moved.'
        }
    } catch {
        throw [InvalidOperationException]::new($_.Exception.Message.Replace($Token,'[REDACTED]'))
    } finally {
        $headers.Remove('Authorization')
        $Token=$null
    }
}
function Invoke-DirectChild($State, [string]$Executable, [string[]]$Arguments, [string]$GitHubToken = '') {
    if ($State.toolHashes.ContainsKey($Executable)) { Assert-DirectHash $Executable $State.toolHashes[$Executable] }
    if ($GitHubToken -and ($Executable -cne $State.mise -or
        (Get-Json $Arguments) -cne (Get-Json @('install','--locked','uv')))) {
        throw 'GitHub credentials are restricted to the official install subprocess.'
    }
    # 環境全体は引き継がず、取得した認証だけを公式Installの子プロセスへ渡す。
    $psi=[Diagnostics.ProcessStartInfo]::new($Executable)
    $psi.UseShellExecute=$false
    $psi.WorkingDirectory=Join-Path $State.recovery 'work'
    $psi.RedirectStandardOutput=$true; $psi.RedirectStandardError=$true
    $psi.Environment.Clear()
    foreach ($key in @('SystemRoot','WINDIR','COMSPEC','PATHEXT','USERPROFILE','LOCALAPPDATA','APPDATA')) {
        $value=[Environment]::GetEnvironmentVariable($key)
        if ($value) { $psi.Environment[$key]=$value }
    }
    $psi.Environment['PATH']=(Split-Path $State.mise) + ';' + (Join-Path $env:SystemRoot 'System32')
    $psi.Environment['TEMP']=Join-Path $State.recovery 'work\temp'
    $psi.Environment['TMP']=$psi.Environment['TEMP']
    foreach ($pair in (Get-DirectEnvironment $State).GetEnumerator()) { $psi.Environment[$pair.Key]=$pair.Value }
    if ($GitHubToken) { $psi.Environment['GITHUB_TOKEN']=$GitHubToken }
    foreach ($arg in $Arguments) { $psi.ArgumentList.Add($arg) }
    $process=$null
    try {
        $process=[Diagnostics.Process]::Start($psi)
        $out=$process.StandardOutput.ReadToEndAsync(); $err=$process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        if ($State.toolHashes.ContainsKey($Executable)) { Assert-DirectHash $Executable $State.toolHashes[$Executable] }
        $stdout=$out.GetAwaiter().GetResult(); $stderr=$err.GetAwaiter().GetResult()
        if ($GitHubToken) {
            $stdout=$stdout.Replace($GitHubToken,'[REDACTED]'); $stderr=$stderr.Replace($GitHubToken,'[REDACTED]')
        }
        return @{exitCode=$process.ExitCode;stdout=$stdout;stderr=$stderr}
    } catch {
        if ($GitHubToken) { throw [InvalidOperationException]::new($_.Exception.Message.Replace($GitHubToken,'[REDACTED]')) }
        throw
    } finally {
        if ($null -ne $process) { $process.Dispose() }
        $null=$psi.Environment.Remove('GITHUB_TOKEN')
        $GitHubToken=$null
    }
}
function Save-DirectEvent($State, $Journal) {
    $Journal.sequence++
    $path=Join-Path $State.recovery ('events\{0:D6}.json' -f $Journal.sequence)
    Write-NewJson $path $Journal
    $Journal.previous=Get-Hash $path
}
function Read-DirectJournal($State) {
    $previous=$State.digest; $sequence=0; $journal=$null
    foreach ($file in @(Get-ChildItem -LiteralPath (Join-Path $State.recovery 'events') -Force | Sort-Object Name)) {
        $sequence++
        if ($file.Name -cne ('{0:D6}.json' -f $sequence)) { throw 'Unexpected journal entry.' }
        $null=Read-Tree $file.FullName
        $value=Read-Json $file.FullName
        if ($value.sequence -ne $sequence -or $value.previous -cne $previous) { throw 'Broken journal digest chain.' }
        $journal=$value; $previous=Get-Hash $file.FullName
    }
    if ($null -eq $journal) { throw 'Preparation incomplete: no mutation journal.' }
    $journal.previous=$previous
    return $journal
}
function Assert-DirectGuards($State) {
    foreach ($path in $State.guards.Keys) { Assert-Equal (Read-Tree $path) $State.guards[$path] 'Unexpected protected-object change.' }
    foreach ($path in $State.parents.Keys) { Assert-Equal (Read-Parent $path) $State.parents[$path] 'Unexpected parent change.' }
    $names=@(Get-ChildItem -LiteralPath (Join-Path $State.roots.data 'installs\uv') -Force |
        ForEach-Object Name | Where-Object { $_ -notin $State.uvNames } | Sort-Object)
    Assert-Equal $names @() 'Unexpected uv child; no traversal or deletion is allowed.'
    $retained=@(Get-ChildItem -LiteralPath (Join-Path $State.roots.data 'installs\uv') -Force |
        ForEach-Object Name | Where-Object { $_ -in $State.outsideScopeNames } | Sort-Object)
    Assert-Equal $retained @($State.outsideScopeNames | Sort-Object) 'Retained evidence name disappeared.'
    $tools=@(Get-ChildItem -LiteralPath (Join-Path $State.roots.data 'installs') -Force -Directory | ForEach-Object Name | Sort-Object)
    Assert-Equal $tools $State.installNames 'Install-root directory set changed.'
    foreach ($path in $State.sealed.Keys) { Assert-Equal (Read-Tree $path) $State.sealed[$path] 'Recovery input changed.' }
}
function Assert-DirectCurrent($State, $Journal, [string]$ExceptTarget = '') {
    Assert-DirectGuards $State
    foreach ($entry in $State.entries) {
        if ($entry.target -ceq $ExceptTarget) { continue }
        Assert-Equal (Read-Tree $entry.target) $Journal.current[$entry.target] 'Unexpected writer-scope change.'
        $saved=Join-Path $State.recovery $entry.saved
        $expected=if ($Journal.saved[$entry.target]) { $entry.original } else { @{kind='absent';nodes=@()} }
        Assert-Equal (Read-Tree $saved) $expected 'Original backup changed.'
    }
}
function Move-DirectRecorded($State, $Journal, [string]$From, [string]$To, $Expected,
        [string]$Target, [string]$Effect) {
    $Journal.pending=@{kind='rename';from=$From;to=$To;expected=$Expected;target=$Target;effect=$Effect}
    Save-DirectEvent $State $Journal
    Move-Tree $From $To $Expected
    Complete-DirectRename $State $Journal
}
function Complete-DirectRename($State, $Journal) {
    $pending=$Journal.pending
    $absent=@{kind='absent';nodes=@()}
    $from=Read-Tree $pending.from; $to=Read-Tree $pending.to
    if ((Get-Json $from) -ceq (Get-Json $pending.expected) -and $to.kind -eq 'absent') {
        Move-Tree $pending.from $pending.to $pending.expected
    } elseif ($from.kind -ne 'absent' -or (Get-Json $to) -cne (Get-Json $pending.expected)) {
        throw 'Ambiguous interrupted rename; no overwrite or rebaseline.'
    }
    switch ($pending.effect) {
        'save' { $Journal.saved[$pending.target]=$true; $Journal.current[$pending.target]=$absent }
        'empty' { $Journal.current[$pending.target]=$absent }
        'publish' { $Journal.current[$pending.target]=$pending.expected }
        'restore' { $Journal.current[$pending.target]=$pending.expected; $Journal.saved[$pending.target]=$false }
        default { throw 'Invalid rename effect.' }
    }
    $Journal.pending=$null
    Save-DirectEvent $State $Journal
}
function New-DirectRecorded($State, $Journal, $Entry, [scriptblock]$Create) {
    if ($Journal.current[$Entry.target].kind -ne 'absent') { throw 'Creation target is not vacant.' }
    $Journal.pending=@{kind='create';target=$Entry.target}
    Save-DirectEvent $State $Journal
    & $Create
    $Journal.current[$Entry.target]=Read-Tree $Entry.target
    $Journal.pending=$null
    Save-DirectEvent $State $Journal
}
function Get-DirectEntry($State, [string]$Role) {
    $found=@($State.entries | Where-Object role -CEQ $Role)
    if ($found.Count -ne 1) { throw 'Missing/ambiguous recovery role.' }
    return $found[0]
}
function Prepare-DirectInterruptedRestore($State, $Journal) {
    Assert-DirectGuards $State
    $targets=@()
    if ($null -ne $Journal.pending) {
        if ($Journal.pending.kind -cne 'create' -or $Journal.phase -cne 'preserving') {
            throw 'Unsupported interrupted operation; preserve the journal.'
        }
        $targets=@($State.entries | Where-Object { $_.target -ceq $Journal.pending.target })
        if ($targets.Count -ne 1 -or $targets[0].role -notin @('manifest','backend','legacy','cache')) {
            throw 'Interrupted creation is outside the recorded write scope.'
        }
        Assert-Equal $Journal.current[$targets[0].target] @{kind='absent';nodes=@()} 'Creation was not recorded as vacant.'
    } elseif ($Journal.phase -ceq 'installer-started') {
        $targets=@($State.entries | Where-Object { $_.role -notin @('config','lock','cache') })
    } else {
        throw 'No unsealed interrupted operation to quarantine.'
    }
    $observed=@{}
    foreach ($entry in $State.entries) {
        $saved=Join-Path $State.recovery $entry.saved
        $expected=if ($Journal.saved[$entry.target]) { $entry.original } else { @{kind='absent';nodes=@()} }
        Assert-Equal (Read-Tree $saved) $expected 'Original backup changed.'
        if ($entry.target -cin @($targets.target)) {
            if ($entry.original.kind -ne 'absent' -and -not $Journal.saved[$entry.target]) {
                throw 'Original object was not preserved before the interrupted write.'
            }
            $observed[$entry.target]=Read-Tree $entry.target
        } else {
            Assert-Equal (Read-Tree $entry.target) $Journal.current[$entry.target] 'Unexpected change outside interrupted write scope.'
        }
    }
    # 作者不明の内容を導入結果とは認めず、明示承認された退避対象としてだけ記録する。
    # 元オブジェクトと対象外は上で照合済み。移動前にも同じ観測値を要求する。
    foreach ($path in $observed.Keys) {
        Assert-Equal (Read-Tree $path) $observed[$path] 'Interrupted output is still changing; stop all writers.'
    }
    $Journal.interruptedRestore=@{
        disposition='quarantine_only_provenance_unknown';phase=$Journal.phase
        pending=$Journal.pending;observations=$observed
    }
    foreach ($path in $observed.Keys) { $Journal.current[$path]=$observed[$path] }
    $Journal.pending=$null
    $Journal.phase='restoring-interrupted'
    Save-DirectEvent $State $Journal
}
function Restore-Direct($State, $Journal, [switch]$QuarantineInterruptedOutputs) {
    if ($Journal.phase -ceq 'restored') { throw 'Restored journal cannot be reused.' }
    if (($null -ne $Journal.pending -and $Journal.pending.kind -ceq 'create') -or
        ($null -eq $Journal.pending -and $Journal.phase -ceq 'installer-started')) {
        if (-not $QuarantineInterruptedOutputs) {
            throw 'Unsealed interrupted outputs. Stop all child processes. Explicit -QuarantineInterruptedOutputs is required to retain these unknown-provenance objects and restore originals.'
        }
        Prepare-DirectInterruptedRestore $State $Journal
    }
    if ($null -ne $Journal.pending) {
        if ($Journal.pending.kind -cne 'rename') { throw 'Unsealed creation; offline Restore refuses ambiguous output.' }
        Assert-DirectCurrent $State $Journal $Journal.pending.target
        Complete-DirectRename $State $Journal
    }
    if ($Journal.phase -ceq 'installer-started') {
        throw 'Installer outcome is unsealed. Stop its process tree; preserve the live incomplete marker. No automatic adoption or retry.'
    }
    Assert-DirectCurrent $State $Journal
    $Journal.phase='restoring'; Save-DirectEvent $State $Journal
    # 不完全markerを持つ実cacheは最後に戻す。途中停止でも部分installを導入済みに見せない。
    $ordered=@($State.entries | Where-Object role -CNE 'cache') + @($State.entries | Where-Object role -CEQ 'cache')
    foreach ($entry in $ordered) {
        if (-not $Journal.saved[$entry.target] -and $entry.original.kind -ne 'absent') { continue }
        $current=$Journal.current[$entry.target]
        if ($current.kind -ne 'absent') {
            $quarantine=Join-Path $State.recovery ('quarantine\{0}-{1}' -f $Journal.sequence,$entry.id)
            Move-DirectRecorded $State $Journal $entry.target $quarantine $current $entry.target 'empty'
        }
        if ($Journal.saved[$entry.target]) {
            Move-DirectRecorded $State $Journal (Join-Path $State.recovery $entry.saved) $entry.target $entry.original $entry.target 'restore'
        }
    }
    Assert-DirectCurrent $State $Journal
    foreach ($entry in $State.entries) { Assert-Equal (Read-Tree $entry.target) $entry.original 'Original identity/metadata not restored.' }
    $Journal.phase='restored'; Save-DirectEvent $State $Journal
}

function Initialize-DirectRecovery {
    Assert-DirectEnvironment
    Assert-DirectHash $Report $ReportDigest
    $inventoryReport=Read-Json $Report
    if ($inventoryReport.format -cne 'windows-uv-direct-inventory' -or $inventoryReport.schema -ne 1 -or
        $inventoryReport.expectedVersion -cne '0.12.10' -or $inventoryReport.canApply -ne $false -or
        $inventoryReport.installerInvoked -ne $false -or $inventoryReport.originalsMoved -ne $false) {
        throw 'Unsupported original inventory contract.'
    }
    Assert-DirectSource $Source $SourceCommit $PSScriptRoot
    Assert-Equal (Get-DirectScripts $PSScriptRoot) (Get-DirectScripts (Join-Path $Source 'tests\manual\windows-uv')) 'Running source hash mismatch.'
    $roots=Get-Json $inventoryReport.roots | ConvertFrom-Json -AsHashtable
    Assert-Equal (Split-Path $Recovery) (Split-Path $roots.recovery) 'Fresh recovery must use the same inventoried parent.'
    $roots.recovery=$Recovery
    Assert-DirectFreshRecoveryParent $Recovery
    if (Test-Path -LiteralPath $Recovery) { throw 'Recovery must be new.' }
    foreach ($path in @($Source,(Split-Path $roots.config),$roots.data,$roots.cache,$Report)) {
        if ($Recovery -ieq $path -or
            $Recovery.StartsWith($path.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase) -or
            $path.StartsWith($Recovery.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) {
            throw 'Recovery overlaps protected inputs.'
        }
    }
    $lock=Join-Path (Split-Path $roots.config) 'mise.lock'
    foreach ($path in @($roots.config,$lock)) {
        Assert-Equal (Read-Tree $path) $inventoryReport.inputs[$path] 'Original input changed since inventory.'
    }
    foreach ($path in $inventoryReport.parents.Keys) {
        Assert-Equal (Read-Parent $path) $inventoryReport.parents[$path] 'Inventory parent changed.'
    }
    foreach ($path in $inventoryReport.toolHashes.Keys) { Assert-DirectHash $path $inventoryReport.toolHashes[$path] }
    $mise=(Get-Command mise -CommandType Application -TotalCount 1).Source
    $chezmoi=(Get-Command chezmoi -CommandType Application -TotalCount 1).Source
    foreach ($path in @($mise,$chezmoi)) {
        if (-not $inventoryReport.toolHashes.ContainsKey($path)) { throw 'Tool resolution differs from inventory.' }
    }
    Assert-DirectSourceInputs $Source $inventoryReport.inputs
    $original=ConvertFrom-Toml ([IO.File]::ReadAllText($roots.config)) $chezmoi $Source
    $oldLock=ConvertFrom-Toml ([IO.File]::ReadAllText($lock)) $chezmoi $Source
    $candidateLock=Assert-DirectLock $oldLock (ConvertFrom-Toml ([IO.File]::ReadAllText(
        (Join-Path $Source 'home\dot_config\mise\private_mise.lock'))) $chezmoi $Source) '0.12.10'
    $declaration=@{version='latest';platforms=@{'windows-arm64'=@{asset_pattern='uv-x86_64-pc-windows-msvc.zip'}}}
    $candidateConfig=Get-DirectCandidateConfig $original $declaration
    Assert-Equal (Get-DirectDigest $candidateConfig) $inventoryReport.proposedConfigDigest 'Candidate config digest mismatch.'
    Assert-Equal (Get-DirectDigest $candidateLock) $inventoryReport.proposedLockDigest 'Candidate lock digest mismatch.'
    $installs=Join-Path $roots.data 'installs'
    $inventory=Get-DirectInventory $installs $roots.cache (Join-Path $roots.data 'downloads') $original
    Assert-Equal $inventory $inventoryReport.inventory 'Inventory changed; do not rebaseline.'
    Assert-DirectPointers $inventory
    Assert-DirectMetadata $inventoryReport.metadata $inventory $installs
    foreach ($key in $original.settings.Keys) {
        if ($key -notin @('experimental','lockfile','minimum_release_age','minimum_release_age_excludes',
                'fetch_remote_versions_timeout','lockfile_platforms')) {
            throw 'Original settings contain an unsupported child-install control; no silent setting removal.'
        }
    }
    foreach ($key in $original.Keys) {
        if ($key -notin @('tools','tool_alias','settings')) {
            throw 'Original config has unreviewed environment, hook, alias or task sections.'
        }
    }
    # 上流の全体初期化を狭める。plugins/shared installsは新規の空ディレクトリを明示する。
    $childConfig=@{tools=@{uv=$declaration};tool_alias=@{uv='github:astral-sh/uv'};settings=@{experimental=$true;lockfile=$true}}
    foreach ($key in @('minimum_release_age','minimum_release_age_excludes','fetch_remote_versions_timeout','lockfile_platforms')) {
        if ($original.settings.ContainsKey($key)) { $childConfig.settings[$key]=$original.settings[$key] }
    }
    $entries=[Collections.Generic.List[object]]::new()
    $targets=@(
        @{role='version';path=(Join-Path $installs 'uv\0.12.10');tree=$inventory.versions['0.12.10']}
        @{role='manifest';path=(Join-Path $installs '.mise-installs.toml');tree=$inventory.sharedManifest}
        @{role='backend';path=(Join-Path $installs 'uv\.mise.backend.toml');tree=$inventory.uvBackend}
        @{role='cache';path=(Join-Path $roots.cache 'uv');tree=$inventory.uvCache}
        @{role='downloads';path=(Join-Path $roots.data 'downloads\uv');tree=$inventory.uvDownloads}
        @{role='config';path=$roots.config;tree=$inventoryReport.inputs[$roots.config]}
        @{role='lock';path=$lock;tree=$inventoryReport.inputs[$lock]}
    )
    foreach ($name in $inventory.runtimeSlots.Keys | Sort-Object) {
        $targets+=@{role='pointer';path=(Join-Path $installs "uv\$name");tree=$inventory.runtimeSlots[$name].state}
    }
    foreach ($name in $inventory.otherLegacyMetadata.Keys | Sort-Object) {
        if ($inventory.otherLegacyMetadata[$name].kind -eq 'file') {
            $targets+=@{role='legacy';path=(Join-Path $installs "$name\.mise.backend.toml");tree=$inventory.otherLegacyMetadata[$name]}
        }
    }
    $parents=@{}; $guards=@{}
    foreach ($target in $targets) {
        $id='{0:D3}' -f $entries.Count
        $entries.Add(@{id=$id;role=$target.role;target=$target.path;original=$target.tree;saved="originals\$id"})
        $parent=Split-Path $target.path
        $parents[$parent]=Read-Parent $parent
    }
    foreach ($path in @($roots.data,$roots.cache,$installs)) { $parents[$path]=Read-Parent $path }
    foreach ($version in $inventory.versions.Keys | Where-Object { $_ -cne '0.12.10' }) {
        $guards[(Join-Path $installs "uv\$version")]=$inventory.versions[$version]
    }
    foreach ($name in $inventory.otherLegacyMetadata.Keys) {
        if ($inventory.otherLegacyMetadata[$name].kind -eq 'absent') {
            $guards[(Join-Path $installs "$name\.mise.backend.toml")]=$inventory.otherLegacyMetadata[$name]
        }
    }
    $guards[$Report]=Read-Tree $Report
    New-ExclusiveDirectory $Recovery
    foreach ($dir in @('originals','events','quarantine','publish','work','work\config','work\cache',
            'work\state','work\shims','work\plugins','work\system','work\temp')) {
        New-ExclusiveDirectory (Join-Path $Recovery $dir)
    }
    foreach ($name in (Get-DirectScripts $PSScriptRoot).Keys) {
        Write-DirectBytes (Join-Path $Recovery $name) ([IO.File]::ReadAllBytes((Join-Path $PSScriptRoot $name)))
    }
    $sealed=@{}
    foreach ($name in (Get-DirectScripts $PSScriptRoot).Keys) {
        $path=Join-Path $Recovery $name
        $sealed[$path]=Read-Tree $path
    }
    foreach ($dir in @('','originals','events','quarantine','publish','work','work\config','work\cache',
            'work\state','work\shims','work\plugins','work\system','work\temp')) {
        $path=if ($dir) { Join-Path $Recovery $dir } else { $Recovery }
        $parents[$path]=Read-Parent $path
    }
    $files=@{
        'publish\config.toml'=$candidateConfig; 'publish\mise.lock'=$candidateLock
        'work\config\config.toml'=$childConfig; 'work\config\mise.lock'=$candidateLock
        'work\system\config.toml'=@{}
    }
    foreach ($name in $files.Keys) {
        $path=Join-Path $Recovery $name
        Write-DirectBytes $path ([Text.Encoding]::UTF8.GetBytes((ConvertTo-DirectToml $files[$name] $chezmoi $Source)))
        Assert-Equal (ConvertFrom-Toml ([IO.File]::ReadAllText($path)) $chezmoi $Source) $files[$name] 'TOML round-trip mismatch.'
        if ($name -like 'work\*') { $sealed[$path]=Read-Tree $path }
    }
    $state=@{
        format='windows-uv-direct-recovery';schema=1;recovery=$Recovery;roots=$roots
        sourceCommit=$SourceCommit;inventoryCommit=$inventoryReport.sourceCommit;reportDigest=$ReportDigest
        scripts=(Get-DirectScripts $Recovery);entries=@($entries.ToArray());parents=$parents;guards=$guards;sealed=$sealed
        uvNames=@(@($inventory.versions.Keys)+@($inventory.runtimeSlots.Keys)+@('.mise.backend.toml')+@($inventory.outsideScopeNames))
        outsideScopeNames=$inventory.outsideScopeNames
        installNames=@(Get-ChildItem -LiteralPath $installs -Force -Directory | ForEach-Object Name | Sort-Object)
        metadata=$inventoryReport.metadata;mise=$mise;chezmoi=$chezmoi;toolHashes=$inventoryReport.toolHashes
        attestationDigest=(@($candidateLock.tools.uv | Where-Object { $_.ContainsKey('platforms.windows-x64') })[0]['platforms.windows-x64'].checksum)
        publication=@{config=(Read-Tree (Join-Path $Recovery 'publish\config.toml'));lock=(Read-Tree (Join-Path $Recovery 'publish\mise.lock'))}
        upstreamCommit='a51a56b70b5172610e860ca356e3033e3b67c595';sacl='unobserved'
    }
    Assert-DirectGuards $state
    foreach ($entry in $state.entries) { Assert-Equal (Read-Tree $entry.target) $entry.original 'Original changed during Prepare.' }
    Assert-DirectSource $Source $SourceCommit $PSScriptRoot
    Assert-DirectHash $Report $ReportDigest
    foreach ($path in $state.toolHashes.Keys) { Assert-DirectHash $path $state.toolHashes[$path] }
    Write-NewJson (Join-Path $Recovery 'direct-snapshot.json') $state
    $state.digest=Get-Hash (Join-Path $Recovery 'direct-snapshot.json')
    $current=@{}; $saved=@{}
    foreach ($entry in $state.entries) { $current[$entry.target]=$entry.original; $saved[$entry.target]=$false }
    $journal=@{sequence=0;previous=$state.digest;phase='prepared';pending=$null;current=$current;saved=$saved}
    Save-DirectEvent $state $journal
    return $state
}

function Install-Direct($State, $Journal) {
    if ($Journal.phase -cne 'prepared' -or $null -ne $Journal.pending) { throw 'Install is one-shot; never retry a started migration.' }
    Assert-DirectEnvironment
    Assert-DirectCurrent $State $Journal
    foreach ($path in $State.toolHashes.Keys) { Assert-DirectHash $path $State.toolHashes[$path] }
    $version=Invoke-DirectChild $State $State.mise @('--version')
    if ($version.exitCode -ne 0 -or $version.stdout -notmatch '^2026\.8\.5(?:\s|$)') { throw 'Only mise 2026.8.5 is supported.' }
    Assert-DirectCurrent $State $Journal
    $token=Get-DirectGitHubToken (Join-Path $State.recovery 'work')
    try {
        Assert-DirectGitHubAccess $token $State.attestationDigest
        Assert-DirectCurrent $State $Journal
        Install-DirectAuthenticated $State $Journal $token
    } finally { $token=$null }
}
function Install-DirectAuthenticated($State, $Journal, [string]$Token) {
    $Journal.phase='preserving'; Save-DirectEvent $State $Journal
    foreach ($entry in $State.entries | Where-Object { $_.role -notin @('config','lock') }) {
        if ($entry.original.kind -ne 'absent') {
            Move-DirectRecorded $State $Journal $entry.target (Join-Path $State.recovery $entry.saved) $entry.original $entry.target 'save'
        }
        if ($entry.role -in @('manifest','backend','legacy')) {
            New-DirectRecorded $State $Journal $entry {
                Write-DirectBytes $entry.target ([IO.File]::ReadAllBytes((Join-Path $State.recovery $entry.saved)))
            }
        } elseif ($entry.role -ceq 'cache') {
            # 実cacheのmarkerは子cacheと独立して保持し、失敗/クラッシュ時の通常miseの誤判定を防ぐ。
            New-DirectRecorded $State $Journal $entry {
                New-ExclusiveDirectory $entry.target
                New-ExclusiveDirectory (Join-Path $entry.target '0.12.10')
                Write-DirectBytes (Join-Path $entry.target '0.12.10\incomplete') ([byte[]]@())
            }
        }
    }
    Assert-DirectCurrent $State $Journal
    $Journal.phase='installer-started'; Save-DirectEvent $State $Journal
    $result=Invoke-DirectChild $State $State.mise @('install','--locked','uv') $Token
    # 出力は非公開Recoveryへだけ保存し、失敗内容を端末へ展開しない。
    Write-NewJson (Join-Path $State.recovery 'installer-result.json') $result
    foreach ($entry in $State.entries | Where-Object { $_.role -notin @('config','lock','cache') }) {
        $Journal.current[$entry.target]=Read-Tree $entry.target
    }
    $Journal.exitCode=$result.exitCode
    $Journal.phase='installer-exited'; Save-DirectEvent $State $Journal
    Assert-DirectCurrent $State $Journal
    if ($result.exitCode -ne 0) {
        [Console]::Error.WriteLine("mise install exit: $($result.exitCode)")
        [Console]::Error.WriteLine($result.stderr)
        [Console]::Error.WriteLine($result.stdout)
        throw 'Official install failed. Outputs retained and sealed; run offline Restore, not Install.'
    }
    Confirm-DirectInstall $State $Journal
    foreach ($entry in $State.entries | Where-Object role -CEQ 'legacy') {
        Move-DirectRecorded $State $Journal $entry.target (Join-Path $State.recovery "quarantine\legacy-$($entry.id)") `
            $Journal.current[$entry.target] $entry.target 'empty'
        Move-DirectRecorded $State $Journal (Join-Path $State.recovery $entry.saved) $entry.target $entry.original $entry.target 'restore'
    }
    $Journal.phase='publishing'; Save-DirectEvent $State $Journal
    foreach ($role in @('config','lock')) {
        $entry=Get-DirectEntry $State $role
        $name=if ($role -ceq 'config') {'config.toml'} else {'mise.lock'}
        $candidate=Join-Path $State.recovery "publish\$name"
        Assert-Equal (Read-Tree $candidate) $State.publication[$role] 'Publication candidate changed.'
        Move-DirectRecorded $State $Journal $entry.target (Join-Path $State.recovery $entry.saved) $entry.original $entry.target 'save'
        Move-DirectRecorded $State $Journal $candidate $entry.target $State.publication[$role] $entry.target 'publish'
    }
    # cacheのみを公開する。実行バイナリは公式miseがcanonical pathに直接生成したものを保持する。
    $cacheEntry=Get-DirectEntry $State 'cache'
    $childCache=Join-Path $State.recovery 'work\cache\uv'
    $cacheTree=Read-Tree $childCache
    if ($cacheTree.kind -ne 'directory' -or (Test-Path -LiteralPath (Join-Path $childCache '0.12.10\incomplete'))) {
        throw 'Successful child cache is missing or incomplete; live incomplete marker retained.'
    }
    Move-DirectRecorded $State $Journal $cacheEntry.target (Join-Path $State.recovery 'quarantine\live-marker-cache') `
        $Journal.current[$cacheEntry.target] $cacheEntry.target 'empty'
    Move-DirectRecorded $State $Journal $childCache $cacheEntry.target $cacheTree $cacheEntry.target 'publish'
    Assert-DirectCurrent $State $Journal
    $Journal.phase='installed'; Save-DirectEvent $State $Journal
}
function Confirm-DirectInstall($State, $Journal) {
    foreach ($path in $State.toolHashes.Keys) { Assert-DirectHash $path $State.toolHashes[$path] }
    $canonical=(Get-DirectEntry $State 'version').target
    $observations=@()
    foreach ($name in @('uv','uvx')) {
        $path=Join-Path $canonical "$name.exe"
        if ((Read-Tree $path).kind -ne 'file') { throw 'Canonical executable missing.' }
        $which=Invoke-DirectChild $State $State.mise @('which',$name)
        if ($which.exitCode -ne 0 -or $which.stdout.Trim().Replace('/','\') -ine $path.Replace('/','\')) { throw 'mise which did not resolve the canonical executable.' }
        Assert-DirectCurrent $State $Journal
        $run=Invoke-DirectChild $State $path @('--version')
        if ($run.exitCode -ne 0 -or $run.stdout -notmatch ('^'+$name+' 0\.12\.10(?:\s|$)')) { throw 'Canonical executable version verification failed.' }
        $observations+=@{name=$name;path=$path;hash=(Get-Hash $path);version=$run.stdout.Trim()}
    }
    $installs=Join-Path $State.roots.data 'installs'
    $manifest=ConvertFrom-Toml ([IO.File]::ReadAllText((Join-Path $installs '.mise-installs.toml'))) $State.chezmoi $State.recovery
    $before=$State.metadata[(Join-Path $installs '.mise-installs.toml')]
    Assert-Equal (Get-WithoutUv $manifest) (Get-WithoutUv $before) 'Other-tool manifest meaning changed.'
    # tool_aliasの解決先と、利用者がfull backend名を指定したかのフラグは別の情報。
    if ($manifest.uv.explicit_backend -isnot [bool]) { throw 'Invalid installed backend flag.' }
    $expected=@{
        short='uv';full='github:astral-sh/uv';explicit_backend=$manifest.uv.explicit_backend
        opts=@{platforms=@{'windows-arm64'=@{asset_pattern='uv-x86_64-pc-windows-msvc.zip'}}}
    }
    Assert-Equal $manifest.uv $expected 'Unexpected installed uv manifest.'
    foreach ($entry in $State.entries | Where-Object { $_.role -in @('legacy','backend') }) {
        $actual=ConvertFrom-Toml ([IO.File]::ReadAllText($entry.target)) $State.chezmoi $State.recovery
        $desired=if ($entry.role -ceq 'backend') { $expected } else { $State.metadata[$entry.target] }
        Assert-Equal $actual $desired 'Other metadata meaning changed or uv backend incorrect.'
    }
    foreach ($entry in $State.entries | Where-Object role -CEQ 'pointer') {
        $name=Split-Path $entry.target -Leaf
        $expectedPointer=if ($name -ceq '0.11') { '.\0.11.31' } else { '.\0.12.10' }
        Assert-Equal ([IO.File]::ReadAllText($entry.target)) $expectedPointer 'Unexpected official runtime pointer.'
    }
    foreach ($path in $State.toolHashes.Keys) { Assert-DirectHash $path $State.toolHashes[$path] }
    Assert-DirectCurrent $State $Journal
    Write-NewJson (Join-Path $State.recovery 'verification.json') @{executables=$observations;sandboxVerified=$false}
}

Assert-Native
if (-not $WritersStopped) { throw 'Stop all writers and any prior child process tree; -WritersStopped is required.' }
$Recovery=ConvertTo-DirectPath $Recovery
Assert-Beneath $Recovery ([Environment]::GetFolderPath('UserProfile'))
Assert-DirectPrivateParent (Split-Path $Recovery)
$drive=[IO.DriveInfo]::new([IO.Path]::GetPathRoot($Recovery))
if ($drive.DriveFormat -ne 'NTFS' -or $drive.DriveType -ne 'Fixed') { throw 'Same-volume fixed NTFS is required.' }
if ($Command -ceq 'Prepare') {
    $Source=ConvertTo-DirectPath $Source; $Report=ConvertTo-DirectPath $Report
    $state=Initialize-DirectRecovery
    @{status='prepared_not_installed';recovery=$Recovery;recoveryDigest=$state.digest} | ConvertTo-Json -Compress
} else {
    $state=$bootstrap
    $state.digest=$RecoveryDigest.ToUpperInvariant()
    Assert-Equal $state.recovery $Recovery 'Recovery root mismatch.'
    $journal=Read-DirectJournal $state
    try {
        if ($Command -ceq 'Install') { Install-Direct $state $journal }
        else { Restore-Direct $state $journal -QuarantineInterruptedOutputs:$QuarantineInterruptedOutputs }
        @{status=$journal.phase;recovery=$Recovery;recoveryDigest=$state.digest} | ConvertTo-Json -Compress
    } catch {
        $failure=$_
        try {
            Assert-DirectPrivateParent $Recovery
            Write-NewJson (Join-Path $Recovery ('failure-'+[guid]::NewGuid().ToString('N')+'.json')) @{
                phase=$journal.phase;pending=$journal.pending;error=$failure.Exception.ToString()
                stack=$failure.ScriptStackTrace
            }
        } catch {
            [Console]::Error.WriteLine('Failure details could not be saved. Preserve this console output and the recovery directory.')
        }
        [Console]::Error.WriteLine("Direct migration stopped; phase=$($journal.phase); pending=$($null -ne $journal.pending).")
        if ($journal.ContainsKey('exitCode')) { [Console]::Error.WriteLine("mise install exit: $($journal.exitCode)") }
        [Console]::Error.WriteLine($failure.Exception.Message)
        [Console]::Error.WriteLine($failure.InvocationInfo.PositionMessage)
        [Console]::Error.WriteLine($failure.ScriptStackTrace)
        [Console]::Error.WriteLine("Recovery retained: $Recovery")
        exit 1
    }
}
