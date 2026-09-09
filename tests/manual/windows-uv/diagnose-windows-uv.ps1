#requires -Version 7.6
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Backup,
    [Parameter(Mandatory)][string]$SnapshotDigest,
    [Parameter(Mandatory)][string]$PlanDigest,
    [Parameter(Mandatory)][string]$ApprovedUvParent,
    [Parameter(Mandatory)][string]$FixtureRoot,
    [Parameter(Mandatory)][string]$SourceCommit,
    [switch]$WritersStopped
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'uv-state.ps1')

function Copy-DiagnosticTree([string]$Source,[string]$Destination,$Expected,$Desired) {
    Assert-Equal (Read-Tree $Source) $Expected 'Diagnostic input changed'
    $content = Get-Json $Expected | ConvertFrom-Json -AsHashtable
    for ($i=0; $i -lt $content.nodes.Count; $i++) { $content.nodes[$i].sddl=$Desired.nodes[$i].sddl }
    Assert-Observed $content $Desired 'Diagnostic copy requires identical non-ACL metadata'
    Assert-DiagnosticPath $Destination
    foreach ($node in $Expected.nodes) {
        $dest = if ($node.relative) { Join-Path $Destination $node.relative } else { $Destination }
        $src = if ($node.relative) { Join-Path $Source $node.relative } else { $Source }
        Assert-DiagnosticPath $dest
        if ($node.kind -eq 'directory') { New-ExclusiveDirectory $dest }
        else {
            $input = [IO.FileStream]::new($src,'Open','Read','Read')
            try {
                $output = [IO.FileStream]::new($dest,'CreateNew','Write','None')
                try { $input.CopyTo($output); $output.Flush($true) } finally { $output.Dispose() }
            } finally { $input.Dispose() }
        }
    }
    foreach ($node in @($Desired.nodes | Sort-Object { $_.relative.Length } -Descending)) {
        $dest = if ($node.relative) { Join-Path $Destination $node.relative } else { $Destination }
        Assert-DiagnosticPath $dest
        # ACL、owner、groupは書かず、作成先からの継承と観測上の一致を要求する。
        [IO.File]::SetAttributes($dest,[IO.FileAttributes]$node.attributes)
        $item = Get-Item -LiteralPath $dest -Force
        $item.CreationTimeUtc = [datetime]::new([long]$node.created,[DateTimeKind]::Utc)
        $item.LastWriteTimeUtc = [datetime]::new([long]$node.written,[DateTimeKind]::Utc)
    }
    Assert-Observed (Read-Tree $Destination) $Desired 'Inherited diagnostic copy differs'
    Assert-Equal (Read-Tree $Source) $Expected 'Diagnostic input changed during copy'
}
function Assert-DiagnosticPath([string]$Path) {
    Assert-Path $Path -Absent
    foreach ($root in $script:diagnosticRoots) {
        if ($Path -ieq $root -or $Path.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)) { return }
    }
    throw "Outside freshly owned diagnostic paths: $Path"
}
function Get-DiagnosticError($Exception) {
    while ($null -ne $Exception.InnerException -and $Exception -isnot [ComponentModel.Win32Exception]) {
        $Exception=$Exception.InnerException
    }
    @{type=$Exception.GetType().FullName; code=$(if ($Exception -is [ComponentModel.Win32Exception]) {
        $Exception.NativeErrorCode } else { $null })
        operation=$Exception.Data['operation']; source=$Exception.Data['source']
        destination=$Exception.Data['destination']; message=$Exception.Message}
}
function Invoke-DiagnosticMove([string]$Phase,[string]$From,[string]$To,$Before,$After) {
    $event=@{phase=$Phase; source=$From; destination=$To; status='started'; error=$null}
    $script:diagnosticEvents.Add($event)
    $clock=[Diagnostics.Stopwatch]::StartNew()
    try {
        if ($script:diagnosticEvents.Count -gt 4) { throw 'At most four synthetic move phases are allowed' }
        Assert-DiagnosticPath $From
        Assert-DiagnosticPath $To
        if ($From -notin $script:transactionPaths -or $To -notin $script:transactionPaths) {
            throw 'Move requires an exact synthetic transaction path'
        }
        Assert-Equal @(foreach ($path in $script:transactionPaths) { Read-Tree $path }) $Before 'Unexpected pre-move state'
        Move-Tree $From $To $Before[[array]::IndexOf($script:transactionPaths,$From)]
        Assert-Equal @(foreach ($path in $script:transactionPaths) { Read-Tree $path }) $After 'Unexpected post-move state'
        $event.status='passed'
    } catch {
        $event.status='failed'
        $event.error=Get-DiagnosticError $_.Exception
        throw
    } finally {
        $clock.Stop(); $event.elapsedMilliseconds=$clock.Elapsed.TotalMilliseconds
        Write-NewJson (Join-Path $FixtureRoot ("phase-{0}.json" -f $script:diagnosticEvents.Count)) $event
    }
}
function Invoke-DiagnosticTransaction($Old,$New) {
    $live,$retained,$stage,$discard=$script:transactionPaths
    $absent=@{kind='absent';nodes=@()}
    $before=@($Old,$absent,$New,$absent)
    $evacuated=@($absent,$Old,$New,$absent)
    $promoted=@($New,$Old,$absent,$absent)
    $unpublished=@($absent,$Old,$absent,$New)
    $restored=@($Old,$absent,$absent,$New)
    Invoke-DiagnosticMove 'evacuate' $live $retained $before $evacuated
    Invoke-DiagnosticMove 'promote-same-name' $stage $live $evacuated $promoted
    Invoke-DiagnosticMove 'unpublish' $live $discard $promoted $unpublished
    Invoke-DiagnosticMove 'restore-fake-original' $retained $live $unpublished $restored
}
function Read-DiagnosticSiblings {
    $trees=@{}
    foreach ($child in @(Get-ChildItem -LiteralPath $ApprovedUvParent -Force)) {
        if ($child.FullName -notin $script:diagnosticRoots) { $trees[$child.FullName]=Read-Tree $child.FullName }
    }
    return $trees
}
function Read-DiagnosticInputs {
    $files=@{}
    foreach ($name in @(@('snapshot.json','plan.json','journal.json') + @($state.scripts.Keys) | Sort-Object -Unique)) {
        $path=Join-Path $Backup $name
        Assert-Path $path
        $files[$name]=Get-Hash $path
    }
    @{files=$files; original=(Read-Tree $original); candidate=(Read-Tree $candidate)}
}

if (-not $WritersStopped) { throw 'Explicit -WritersStopped is required; diagnostic only.' }
Assert-Native
# Git検証だけを共有し、実移行入口のトップレベル処理は実行しない。
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot 'windows-uv.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Invalid production script syntax' }
foreach ($node in $ast.FindAll({param($n)
    $n -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $n.Name -in @('Get-SourceCommit','ConvertTo-WindowsPath')
},$true)) { . ([scriptblock]::Create($node.Extent.Text)) }
$source=(Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$commit=Get-SourceCommit $source $SourceCommit
$Backup=ConvertTo-WindowsPath $Backup
$FixtureRoot=ConvertTo-WindowsPath $FixtureRoot
$ApprovedUvParent=ConvertTo-WindowsPath $ApprovedUvParent
foreach ($path in @($Backup,$ApprovedUvParent)) { Assert-Path $path }
Assert-Path $FixtureRoot -Absent
if (Test-Path -LiteralPath $FixtureRoot) { throw 'FixtureRoot exists; never reuse evidence.' }
Assert-Beneath $FixtureRoot ([Environment]::GetFolderPath('UserProfile'))
foreach ($root in @($Backup,$ApprovedUvParent,$source)) {
    if ($FixtureRoot -ieq $root -or $FixtureRoot.StartsWith($root.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase) -or
        $root.StartsWith($FixtureRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'FixtureRoot must be independent' }
}
$drive=[IO.DriveInfo]::new([IO.Path]::GetPathRoot($ApprovedUvParent))
if ($drive.DriveFormat -ne 'NTFS' -or $drive.DriveType -ne 'Fixed' -or
    [IO.Path]::GetPathRoot($FixtureRoot) -ine $drive.Name -or
    (Get-ObjectInfo (Split-Path $FixtureRoot)).Volume -ne (Get-ObjectInfo $ApprovedUvParent).Volume) {
    throw 'Diagnostic paths require the same local fixed NTFS volume'
}
$userSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
foreach ($rule in (Get-Acl -LiteralPath (Split-Path $FixtureRoot)).GetAccessRules(
        $true,$true,[Security.Principal.SecurityIdentifier])) {
    if ($rule.AccessControlType -eq 'Allow' -and ([int]$rule.FileSystemRights -band 0x000d0156) -ne 0 -and
        $rule.IdentityReference.Value -notin @($userSid,'S-1-5-18','S-1-5-32-544')) {
        throw 'Fixture parent must already be private; no ACL changes are allowed'
    }
}
Assert-Equal (Get-Hash (Join-Path $Backup 'snapshot.json')) $SnapshotDigest 'Snapshot digest mismatch'
Assert-Equal (Get-Hash (Join-Path $Backup 'plan.json')) $PlanDigest 'Plan digest mismatch'
$state=Read-Json (Join-Path $Backup 'snapshot.json')
$plan=Read-Json (Join-Path $Backup 'plan.json')
$journal=Read-Json (Join-Path $Backup 'journal.json')
if ($state.schema -ne 3 -or $plan.schema -ne 4 -or $journal.phase -ne 'restored') { throw 'Restored schema 3 / plan 4 backup required' }
Assert-Equal $plan.snapshotDigest $SnapshotDigest 'Plan belongs to another snapshot'
Assert-Equal (Split-Path $state.entries[2].target) $ApprovedUvParent 'Approved parent differs from snapshot'
if ((Split-Path $state.entries[2].target -Leaf) -cne '0.12.10') { throw 'Expected uv 0.12.10 target' }
$original=Join-Path $Backup $state.entries[2].saved
$candidate=$plan.entries[2].blob
foreach ($path in @($original,$candidate)) { Assert-Path $path; Assert-Beneath $path $Backup }
foreach ($entry in $state.entries) {
    if ($FixtureRoot -ieq $entry.target -or
        $FixtureRoot.StartsWith($entry.target.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase) -or
        $entry.target.StartsWith($FixtureRoot+'\',[StringComparison]::OrdinalIgnoreCase)) {
        throw 'FixtureRoot must not overlap any real target, including absent targets'
    }
    Assert-Equal (Read-Tree $entry.target) $entry.original 'Real original is not restored'
}
Assert-Equal (Read-Tree $original) $state.entries[2].observation 'Observation copy changed'
Assert-Equal (Read-Tree $candidate) $plan.entries[2].blobState 'Candidate input changed'
if ($state.entries[2].original.kind -ne 'directory' -or $plan.entries[2].after.kind -ne 'directory') {
    throw 'Directory inputs required'
}
$nonce=[guid]::NewGuid().ToString('N')
$live=Join-Path $ApprovedUvParent ".n4-uv-diagnostic-live-$nonce"
$stage=Join-Path $ApprovedUvParent ".n4-uv-diagnostic-stage-$nonce"
$script:diagnosticRoots=@($FixtureRoot,$live,$stage)
$script:transactionPaths=@($live,(Join-Path $FixtureRoot 'retained-original'),$stage,(Join-Path $FixtureRoot 'candidate'))
foreach ($path in @($live,$stage)) {
    Assert-Path $path -Absent
    if (Test-Path -LiteralPath $path) { throw 'Generated diagnostic name already exists' }
}
$backupBefore=Read-DiagnosticInputs
$parentBefore=Read-Parent $ApprovedUvParent
$siblingsBefore=Read-DiagnosticSiblings
$script:diagnosticEvents=[Collections.Generic.List[object]]::new()
$result=@{status='failed'; simulated_only=$true; sandboxSuccess=$false; sourceCommit=$commit
    explicitAclSetterReproduced=$false; paths=$script:transactionPaths; phases=$script:diagnosticEvents
    copies=@(); error=$null; invariantErrors=@()}
New-ExclusiveDirectory $FixtureRoot
try {
    foreach ($copy in @(
        @{phase='copy-original'; source=$original; destination=$live
            expected=$state.entries[2].observation; desired=$state.entries[2].original},
        @{phase='copy-candidate'; source=$candidate; destination=$stage
            expected=$plan.entries[2].blobState; desired=$plan.entries[2].after}
    )) {
        $event=@{phase=$copy.phase; source=$copy.source; destination=$copy.destination; status='started'; error=$null}
        $clock=[Diagnostics.Stopwatch]::StartNew()
        try {
            Copy-DiagnosticTree $copy.source $copy.destination $copy.expected $copy.desired
            $event.status='passed'
        } catch {
            $event.status='failed'; $event.error=Get-DiagnosticError $_.Exception; throw
        } finally {
            $clock.Stop(); $event.elapsedMilliseconds=$clock.Elapsed.TotalMilliseconds
            $result.copies+=$event
            Write-NewJson (Join-Path $FixtureRoot ($copy.phase+'.json')) $event
        }
    }
    $old=Read-Tree $live; $new=Read-Tree $stage
    Write-NewJson (Join-Path $FixtureRoot 'synthetic-state.json') @{
        simulated_only=$true; paths=$script:transactionPaths; original=$old; candidate=$new
    }
    Invoke-DiagnosticTransaction $old $new
    $result.status='synthetic_restored'
} catch {
    $result.error=Get-DiagnosticError $_.Exception
} finally {
    # 失敗後も全入力を検査する。各不一致は記録し、成功扱いや次のrenameを許可しない。
    $checks=@(
        { Assert-Equal (Read-DiagnosticInputs) $backupBefore 'Saved diagnostic inputs changed' },
        { Assert-Equal (Read-Parent $ApprovedUvParent) $parentBefore 'UV parent changed (excluding times)' },
        { Assert-Equal (Read-DiagnosticSiblings) $siblingsBefore 'Pre-existing UV siblings changed' },
        { Assert-Equal (Get-SourceCommit $source $SourceCommit) $commit 'Diagnostic source changed' }
    )
    foreach ($entry in $state.entries) {
        try { Assert-Equal (Read-Tree $entry.target) $entry.original 'Real original changed' }
        catch { $result.invariantErrors+=Get-DiagnosticError $_.Exception }
    }
    foreach ($check in $checks) {
        try { & $check } catch { $result.invariantErrors+=Get-DiagnosticError $_.Exception }
    }
    if ($result.invariantErrors.Count) { $result.status='failed' }
    Write-NewJson (Join-Path $FixtureRoot 'result.json') $result
    Get-Json $result
}
if ($result.status -ne 'synthetic_restored') { exit 1 }
