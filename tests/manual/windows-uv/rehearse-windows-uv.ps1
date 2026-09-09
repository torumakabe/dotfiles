#requires -Version 7.6
[CmdletBinding()]
param([switch]$MockOnly,[string]$NativeRoot,[string]$CaseName)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$results=[Collections.Generic.List[object]]::new()
foreach ($file in @('uv-state.ps1','windows-uv.ps1','rehearse-windows-uv.ps1','run-native-fixture.ps1')) {
    $tokens=$null; $errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $file),[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
    $auditCalls=@($ast.FindAll({
        param($n)
        $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Get-Acl' -and
        @($n.CommandElements | Where-Object {
            $_ -is [Management.Automation.Language.CommandParameterAst] -and $_.ParameterName -eq 'Audit'
        }).Count -gt 0
    },$true))
    if ($auditCalls.Count) { throw "Ordinary-user path requests audit privilege: $file" }
    $results.Add(@{case="parser/no-audit:$file";status='passed';kind='static'})
}
. (Join-Path $PSScriptRoot 'uv-state.ps1')
if (-not (Get-Command New-ExclusiveDirectory -CommandType Function -ErrorAction SilentlyContinue)) {
    throw 'New-ExclusiveDirectory must be defined at script scope.'
}
$results.Add(@{case='function-export:New-ExclusiveDirectory';status='passed';kind='static'})
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'windows-uv.ps1'),[ref]$tokens,[ref]$errors)
foreach ($function in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)) {
    . ([scriptblock]::Create($function.Extent.Text))
}
if (-not $MockOnly) {
    if (-not $IsWindows) {
        @{status='unsupported_os_not_executed';cases=$results;nativeExecuted=$false} | ConvertTo-Json -Depth 10
        exit 2
    }
    Assert-Native
    Assert-Path $NativeRoot -Absent
    if (Test-Path -LiteralPath $NativeRoot) { throw 'NativeRoot must not exist; never reuse evidence.' }
    Assert-Beneath $NativeRoot ([Environment]::GetFolderPath('UserProfile'))
    $drive=[IO.DriveInfo]::new([IO.Path]::GetPathRoot($NativeRoot))
    if ($drive.DriveFormat -ne 'NTFS' -or $drive.DriveType -ne 'Fixed') { throw 'Local fixed NTFS required.' }
    New-ExclusiveDirectory $NativeRoot
}
$script:fixtureNumber=0
$script:identityNumber=0
$script:moveImplementation=${function:Move-Tree}
$script:saveImplementation=${function:Save-Journal}
$script:realSaveImplementation=${function:Save-Journal}
$script:activeCase=$null
$script:selectedCases=0
$script:failure=''
if ($MockOnly) {
    function Read-Tree([string]$Path) {
        if ($script:files.ContainsKey($Path)) { return (Get-Json $script:files[$Path] | ConvertFrom-Json -AsHashtable) }
        return @{kind='absent';nodes=@()}
    }
    function Copy-Tree([string]$Source,[string]$Destination,$Expected) {
        Assert-Equal (Read-Tree $Source) $Expected 'mock source changed'
        if ((Read-Tree $Destination).kind -ne 'absent') { throw 'mock copy destination occupied' }
        if ($Expected.kind -eq 'absent') { return }
        $copy=Get-Json $Expected | ConvertFrom-Json -AsHashtable
        foreach ($node in $copy.nodes) { $node.identity="volume:copy-$($script:identityNumber++)" }
        $script:files[$Destination]=$copy
    }
    function Set-Node([string]$Path,$Node) {
        foreach ($root in $script:files.Keys) {
            foreach ($currentNode in $script:files[$root].nodes) {
                $full = if ($currentNode.relative) { Join-Path $root $currentNode.relative } else { $root }
                if ($full -ceq $Path) {
                    foreach ($field in @('sddl','attributes','created','written')) { $currentNode[$field]=$Node[$field] }
                    return
                }
            }
        }
        throw "Missing mock node: $Path"
    }
    $script:moveImplementation = {
        param([string]$Source,[string]$Destination,$Expected)
        Assert-Equal (Read-Tree $Source) $Expected 'mock move source changed'
        if ((Read-Tree $Destination).kind -ne 'absent') { throw 'mock move destination occupied' }
        if ($Expected.kind -eq 'absent') { throw 'mock cannot move absence' }
        $script:files[$Destination]=$script:files[$Source]
        $null=$script:files.Remove($Source)
        if ($Expected.kind -eq 'file') {
            if ($script:tunneled.ContainsKey($Destination)) {
                $script:files[$Destination].nodes[0].created=$script:tunneled[$Destination]
            }
            $script:tunneled[$Source]=$Expected.nodes[0].created
        }
        Assert-Equal (Read-Tree $Destination) $Expected 'mock post-rename metadata changed'
    }
    $script:saveImplementation = { param($Journal) $script:durableJournal=Get-Json $Journal }
}
function Move-Tree([string]$Source,[string]$Destination,$Expected) {
    $script:moveAttempts++
    if ($script:failure -eq "before-move-$script:moveAttempts") { throw 'injected before rename' }
    & $script:moveImplementation $Source $Destination $Expected
    $script:moves++
    if ($script:failure -eq "after-move-$script:moveAttempts") { throw 'injected after rename' }
}
function Save-Journal($Journal) {
    $script:journalSaveAttempts++
    if ($script:failure -eq 'before-journal') { throw 'injected before journal save' }
    & $script:saveImplementation $Journal
    if ($script:failure -eq 'after-journal') { throw 'injected after durable journal save' }
}
function Reload-Journal($Fixture) {
    $Fixture.journal=if ($MockOnly) { $script:durableJournal | ConvertFrom-Json -AsHashtable }
        else { Read-Json (Join-Path $Backup 'journal.json') }
    $script:failure=''; $script:moveAttempts=0
}
function Check([string]$Name,[scriptblock]$Body) {
    if ($CaseName -and $Name -cne $CaseName) { return }
    $script:activeCase=$Name
    $script:selectedCases++
    & $Body
    $results.Add(@{case=$Name;status='passed';kind=$(if ($MockOnly) { 'mock_not_native' } else { 'native_fixture_not_install' })})
}
function Must-Fail([scriptblock]$Body) {
    $failed=$false
    try { & $Body | Out-Null } catch {
        if ($script:failure -and -not $_.Exception.Message.StartsWith('injected ',[StringComparison]::Ordinal)) {
            throw
        }
        $failed=$true
    }
    if (-not $failed) { throw 'Expected refusal' }
}
function New-TestTree([string]$Path,[string]$Kind,[string]$Content) {
    if ($Kind -eq 'absent') { return }
    if ($MockOnly) {
        $nodes=@(@{relative='';kind=$Kind;hash=$(if ($Kind -eq 'file') { $Content } else { $null })
            sddl='owner:group:DACL';sacl='unobserved';attributes=$(if ($Kind -eq 'file') {32} else {16})
            created=1;written=1;identity="volume:object-$($script:identityNumber++)"})
        if ($Kind -eq 'directory') {
            $nodes+=@{relative='uv.exe';kind='file';hash=$Content;sddl='owner:group:DACL';sacl='unobserved'
                attributes=32;created=1;written=1;identity="volume:object-$($script:identityNumber++)"}
        }
        $script:files[$Path]=@{kind=$Kind;nodes=$nodes}
    } elseif ($Kind -eq 'directory') {
        New-ExclusiveDirectory $Path
        New-ExclusiveDirectory (Join-Path $Path 'nested')
        [IO.File]::WriteAllText((Join-Path $Path 'nested\uv.exe'),$Content)
    } else { [IO.File]::WriteAllText($Path,$Content) }
}
function Fixture([string]$OldKind='directory',[string]$NewKind='file') {
    $script:files=@{}; $script:tunneled=@{}; $script:moves=0; $script:moveAttempts=0; $script:failure=''
    $script:journalSaveAttempts=0
    $script:fixtureNumber++
    $root=if ($MockOnly) { '/mock' } else { Join-Path $NativeRoot "case-$script:fixtureNumber" }
    $script:Backup=Join-Path $root 'backup'
    if (-not $MockOnly) { New-ExclusiveDirectory $root; New-ExclusiveDirectory $Backup }
    $live=Join-Path $root 'live'
    $blob=Join-Path $Backup 'prepared'
    $copy=Join-Path $Backup 'observation'
    New-TestTree $live $OldKind 'old fixture, never executed'
    New-TestTree $blob $NewKind 'new fixture, never executed'
    if ($OldKind -eq 'file' -and $NewKind -eq 'file') {
        foreach ($setting in @(@($live,2020),@($blob,2021))) {
            $tree=Read-Tree $setting[0]
            $tree.nodes[0].created=[datetime]::new($setting[1],1,1,0,0,0,[DateTimeKind]::Utc).Ticks
            Set-Node $setting[0] $tree.nodes[0]
        }
    }
    $old=Read-Tree $live; $unsealed=Read-Tree $blob
    Set-CandidateMetadata $blob $old
    $after=Read-Tree $blob
    Copy-Tree $live $copy $old
    $journal=@{phase='installed';records=@{}}
    Save-Journal $journal
    @{
        state=@{entries=@(@{target=$live;saved='observation';original=$old;after=$after})}
        plan=@{entries=@(@{blob=$blob;after=$after})}
        journal=$journal;old=$old;new=$after;unsealed=$unsealed;live=$live;blob=$blob;copy=$copy;root=$root
    }
}
function Apply-Fixture($Fixture) {
    $null=Get-CurrentStates $Fixture.state $Fixture.plan $Fixture.journal
    Publish-One $Fixture.state $Fixture.journal 0 $Fixture.blob $Fixture.new
}
function Restore-Fixture($Fixture) {
    $null=Get-CurrentStates $Fixture.state $Fixture.plan $Fixture.journal
    Publish-One $Fixture.state $Fixture.journal 0 '' $Fixture.old -Restore
    Assert-Equal (Read-Tree $Fixture.live) $Fixture.old 'Exact original object/observed metadata not restored'
}
function Change-Object([string]$Path,[string]$Field) {
    if ($MockOnly) {
        $script:files[$Path].nodes[-1][$Field]='unknown'
    } elseif ($Field -eq 'identity') {
        $tree=Read-Tree $Path
        $other=Join-Path (Split-Path $Path) ('replacement-' + [guid]::NewGuid().ToString('N'))
        Copy-Tree $Path $other $tree
        & $script:moveImplementation $Path ($other + '-retained') $tree
        & $script:moveImplementation $other $Path (Read-Tree $other)
        Assert-Observed (Read-Tree $Path) $tree 'Replacement should differ only in identity'
    } else {
        $node=(Read-Tree $Path).nodes[-1]
        $file=if ($node.relative) { Join-Path $Path $node.relative } else { $Path }
        $item=Get-Item -LiteralPath $file -Force
        switch ($Field) {
            'hash' { [IO.File]::WriteAllText($file,'unknown concurrent change') }
            'created' { $item.CreationTimeUtc=$item.CreationTimeUtc.AddSeconds(-10) }
            'written' { $item.LastWriteTimeUtc=$item.LastWriteTimeUtc.AddSeconds(-10) }
            'attributes' { [IO.File]::SetAttributes($file,($item.Attributes -bxor [IO.FileAttributes]::Hidden)) }
            'sddl' {
                $acl=Get-Acl -LiteralPath $file
                $acl.SetAccessRuleProtection(-not $acl.AreAccessRulesProtected,$true)
                Set-Acl -LiteralPath $file -AclObject $acl
            }
            default { throw "Unsupported fixture mutation: $Field" }
        }
    }
}
try {
    Check 'stable comparison ignores key order, not values' {
        Assert-Equal @{b=2;a=1} @{a=1;b=2} 'ordering'
        Must-Fail { Assert-Equal @{a=1} @{a=2} 'different' }
    }
    foreach ($pair in @(@('directory','file'),@('file','directory'),@('file','file'),@('absent','file'),@('directory','absent'),@('absent','absent'))) {
        Check "apply/restore identity and idempotence: $($pair -join '/')" {
            $f=Fixture $pair[0] $pair[1]
            Apply-Fixture $f
            Assert-Observed (Read-Tree $f.live) $f.new 'after observation'
            $moves=$script:moves
            Apply-Fixture $f
            Assert-Equal $script:moves $moves 'apply must be no-op'
            # コピーが壊れていても、元オブジェクトによる復元はコピーを参照しない。
            if ($f.old.kind -ne 'absent') { Change-Object $f.copy 'hash' }
            Restore-Fixture $f
            Reload-Journal $f
            $moves=$script:moves
            $journalWrites=$script:journalSaveAttempts
            $script:failure='before-journal'
            Restore-Fixture $f
            $script:failure=''
            Assert-Equal $script:moves $moves 'restore must be no-op'
            Assert-Equal $script:journalSaveAttempts $journalWrites 'Repeated restore must not rewrite journal'
            if ($f.journal.records.Count) {
                Assert-Equal $f.journal.records['0'].direction 'restore' 'Original association lost'
            }
        }
    }
    Check 'file replacement seals original creation time without rewriting the original' {
        $f=Fixture 'file' 'file'
        if ($f.unsealed.nodes[0].created -eq $f.old.nodes[0].created) { throw 'Fixture must start with different creation times' }
        Assert-Equal $f.new.nodes[0].created $f.old.nodes[0].created 'Candidate creation time not normalized'
        Assert-Equal (Read-Tree $f.live) $f.old 'Original metadata changed while preparing candidate'
        Apply-Fixture $f
        Restore-Fixture $f
    }
    Check 'file candidate sealed with different creation time refuses before rename' {
        $f=Fixture 'file' 'file'
        Set-Node $f.blob $f.unsealed.nodes[0]
        $f.new=Read-Tree $f.blob
        $f.state.entries[0].after=$f.new; $f.plan.entries[0].after=$f.new
        Must-Fail { Apply-Fixture $f }
        Assert-Equal $script:moves 0 'Unnormalized candidate caused a rename'
        Assert-Equal $f.journal.records.Count 0 'Unnormalized candidate journaled'
    }
    Check 'unchanged candidate leaves original identity and journal untouched' {
        $f=Fixture
        $f.plan.entries[0]=@{blob=$f.copy;after=(Read-Tree $f.copy)}
        $f.new=$f.plan.entries[0].after; $f.blob=$f.copy; $f.state.entries[0].after=$f.new
        Apply-Fixture $f
        Restore-Fixture $f
        Assert-Equal $script:moves 0 'unchanged target moved'
        Assert-Equal $f.journal.records.Count 0 'unchanged target journaled'
    }
    foreach ($field in @('hash','sddl','attributes','created','written','identity')) {
        Check "unknown original $field refuses before first rename" {
            $f=Fixture
            Change-Object $f.live $field
            Must-Fail { Apply-Fixture $f }
            Assert-Equal $script:moves 0 'Must not evacuate changed original'
        }
    }
    foreach ($oldKind in @('directory','file')) {
      foreach ($point in @('before-journal','after-journal','before-move-1','after-move-1','before-move-2','after-move-2')) {
        Check "interrupted $oldKind/file apply $point restores directly after journal reload" {
            $f=Fixture $oldKind 'file'; $script:failure=$point
            Must-Fail { Apply-Fixture $f }
            Reload-Journal $f
            $moves=$script:moves
            Restore-Fixture $f
            $expected=if ($point -eq 'after-move-2') {2}
                elseif ($point -in @('after-move-1','before-move-2')) {1} else {0}
            Assert-Equal ($script:moves-$moves) $expected 'Restore must not finish candidate publication'
            Reload-Journal $f
            Restore-Fixture $f
        }
      }
      foreach ($point in @('before-journal','after-journal','before-move-1','after-move-1','before-move-2','after-move-2')) {
        Check "interrupted $oldKind/file restore $point resumes after journal reload" {
            $f=Fixture $oldKind 'file'
            Apply-Fixture $f
            $script:moveAttempts=0; $script:failure=$point
            Must-Fail { Restore-Fixture $f }
            Reload-Journal $f
            Restore-Fixture $f
            Reload-Journal $f
            $moves=$script:moves
            Restore-Fixture $f
            Assert-Equal $script:moves $moves 'Repeated recovery moved original again'
        }
      }
      foreach ($point in @('before-move-1','after-move-1','before-move-2','after-move-2')) {
        Check "interrupted $oldKind/file apply $point can resume apply then restore" {
            $f=Fixture $oldKind 'file'; $script:failure=$point
            Must-Fail { Apply-Fixture $f }
            Reload-Journal $f
            Apply-Fixture $f
            Restore-Fixture $f
        }
      }
    }
    foreach ($pair in @(@('absent','file'),@('directory','absent'))) {
        foreach ($operation in @('apply','restore')) {
            foreach ($point in @('before-move-1','after-move-1')) {
                Check "absence interruption $($pair -join '/') $operation $point" {
                    $f=Fixture $pair[0] $pair[1]
                    if ($operation -eq 'restore') { Apply-Fixture $f }
                    $script:moveAttempts=0; $script:failure=$point
                    if ($operation -eq 'apply') { Must-Fail { Apply-Fixture $f } }
                    else { Must-Fail { Restore-Fixture $f } }
                    Reload-Journal $f
                    Restore-Fixture $f
                    Reload-Journal $f
                    $journalWrites=$script:journalSaveAttempts
                    $script:failure='before-journal'
                    Restore-Fixture $f
                    $script:failure=''
                    Assert-Equal $script:journalSaveAttempts $journalWrites 'Repeated absence restore rewrote journal'
                }
            }
        }
    }
    foreach ($location in @('originalSource','stage','live','discard')) {
        foreach ($field in @('hash','identity')) {
            Check "unknown $location $field refuses recovery" {
                $f=Fixture
                if ($location -eq 'stage') {
                    $script:failure='after-move-1'
                    Must-Fail { Apply-Fixture $f }
                } else { Apply-Fixture $f }
                if ($location -eq 'discard') {
                    $script:moveAttempts=0; $script:failure='after-move-1'
                    Must-Fail { Restore-Fixture $f }
                }
                Reload-Journal $f
                $path=if ($location -eq 'live') { $f.live } else { $f.journal.records['0'][$location] }
                Change-Object $path $field
                $moves=$script:moves
                Must-Fail { Restore-Fixture $f }
                Assert-Equal $script:moves $moves 'Unknown object was overwritten'
            }
        }
    }
    Check 'all-target preflight refuses later conflict before first rename' {
        $f=Fixture
        $other=Join-Path $f.root 'other'
        New-TestTree $other 'file' 'concurrent'
        $f.state.entries+=@{target=$other;original=$f.old;after=$f.new}
        $f.plan.entries+=@{blob=$f.blob;after=$f.new}
        Must-Fail { Apply-Fixture $f }
        Assert-Equal $script:moves 0 'Must not mutate first target'
    }
    Check 'unknown live object after original evacuation is never adopted' {
        $f=Fixture; $script:failure='after-move-1'
        Must-Fail { Apply-Fixture $f }
        Reload-Journal $f
        New-TestTree $f.live 'file' 'concurrent'
        Must-Fail { Restore-Fixture $f }
    }
    Check 'unknown desired state in journal refuses' {
        $f=Fixture; Apply-Fixture $f
        $f.journal.records['0'].after.nodes[0].written=0
        Must-Fail { Restore-Fixture $f }
    }
    Check 'original source cannot be redirected to the observation copy' {
        $f=Fixture; Apply-Fixture $f
        $f.journal.records['0'].originalSource=$f.copy
        Must-Fail { Restore-Fixture $f }
    }
    Check 'damaged installer output refuses before original evacuation' {
        $f=Fixture
        Change-Object $f.blob 'hash'
        Must-Fail { Apply-Fixture $f }
        Assert-Equal $script:moves 0 'Damaged candidate caused a rename'
    }
    Check 'failed install and original absence need no recovery moves' {
        $f=Fixture
        $f.plan=$null
        Restore-Fixture $f
        Assert-Equal $script:moves 0 'Untouched original moved'
    }
    Check 'missing retained original refuses without using the observation copy' {
        $f=Fixture; Apply-Fixture $f
        $source=$f.journal.records['0'].originalSource
        & $script:moveImplementation $source ($source + '-missing') (Read-Tree $source)
        $moves=$script:moves
        Must-Fail { Restore-Fixture $f }
        Assert-Equal $script:moves $moves 'Candidate moved despite missing original'
    }
    Check 'restore needs neither installer workspace nor observation copies' {
        $f=Fixture; Apply-Fixture $f
        foreach ($path in @($f.copy,$f.blob)) {
            & $script:moveImplementation $path ($path + '-unavailable') (Read-Tree $path)
        }
        Reload-Journal $f
        Restore-Fixture $f
    }
    Check 'unknown replacement after completed restore refuses repeat restore' {
        $f=Fixture; Apply-Fixture $f; Restore-Fixture $f
        Change-Object $f.live 'identity'
        Reload-Journal $f
        $moves=$script:moves
        Must-Fail { Restore-Fixture $f }
        Assert-Equal $script:moves $moves 'Replaced restored original was overwritten'
    }
    Check 'injected interruption never hides an unrelated Windows failure' {
        $f=Fixture
        $script:failure='after-move-1'
        $caught=$null
        try { Must-Fail { throw [ComponentModel.Win32Exception]::new(32,'Unrelated journal failure') } }
        catch [ComponentModel.Win32Exception] { $caught=$_.Exception }
        if ($null -eq $caught) { throw 'Unrelated Windows failure was mistaken for an injected interruption' }
        Assert-Equal $caught.NativeErrorCode 32 'Unrelated native error lost'
        Must-Fail { throw 'injected after rename' }
        $script:failure=''
    }
    foreach ($nativeCode in @(5,32)) {
        Check "journal replacement Win32 $nativeCode is retained without retry or object moves" {
            $f=Fixture
            $saved=if ($MockOnly) { $script:durableJournal } else { Get-Json (Read-Json (Join-Path $Backup 'journal.json')) }
            & {
                $script:journalRenameAttempts=0
                function Invoke-JournalRename([string]$Source,[string]$Destination) {
                    $script:journalRenameAttempts++
                    return $nativeCode
                }
                if ($MockOnly) {
                    function Write-NewJson([string]$Path,$Value) {
                        if (-not $Path.StartsWith((Join-Path $Backup 'journal-'))) { throw 'Unexpected staging path' }
                    }
                }
                $f.journal.phase='restoring'
                $caught=$null
                try { & $script:realSaveImplementation $f.journal }
                catch [ComponentModel.Win32Exception] { $caught=$_.Exception }
                if ($null -eq $caught) { throw 'Native error was not propagated' }
                Assert-Equal $caught.NativeErrorCode $nativeCode 'Native error code lost'
                Assert-Equal $caught.Data['operation'] 'MoveFileExW: journal replacement' 'Operation missing'
                Assert-Equal $caught.Data['destination'] (Join-Path $Backup 'journal.json') 'Destination missing'
                Assert-Equal $script:journalRenameAttempts 1 'Journal replacement retried'
            }
            $current=if ($MockOnly) { $script:durableJournal } else { Get-Json (Read-Json (Join-Path $Backup 'journal.json')) }
            Assert-Equal $current $saved 'Failed replacement changed durable journal'
            Assert-Equal (Read-Tree $f.live) $f.old 'Failed journal save changed original'
            Assert-Equal $script:moves 0 'Failed journal save moved an object'
        }
    }
    if (-not $MockOnly) {
        Check 'readonly rejected without clearing attributes' {
            $f=Fixture 'file'
            [IO.File]::SetAttributes($f.live,[IO.FileAttributes]::ReadOnly)
            Must-Fail { Read-Tree $f.live }
        }
        Check 'junction rejected before traversal' {
            $f=Fixture
            $path=Join-Path $f.root 'junction'
            $null=New-Item -ItemType Junction -Path $path -Target $f.live
            Must-Fail { Read-Tree $path }
        }
        Check 'hardlink rejected' {
            $f=Fixture 'file'
            $null=New-Item -ItemType HardLink -Path (Join-Path $f.root 'alias') -Target $f.live
            Must-Fail { Read-Tree $f.live }
        }
        Check 'alternate data stream rejected' {
            $f=Fixture 'file'
            Set-Content -LiteralPath $f.live -Stream 'n4-test' -Value 'fixture stream'
            Must-Fail { Read-Tree $f.live }
        }
    }
    if ($CaseName -and $script:selectedCases -ne 1) { throw "Unknown or non-unique case name: $CaseName" }
    @{status=$(if ($MockOnly) {'mock_passed'} else {'native_fixture_passed_not_install'})
        nativeExecuted=(-not $MockOnly);cases=$results;count=$results.Count;sacl='unobserved';selectedCase=$CaseName
        scope=$(if ($MockOnly) {'Parser and in-memory transitions only; no Windows API or installer.'}
            else {'Dedicated retained fixtures only; no real install, ARM64 emulation or sandbox validation.'})} |
        ConvertTo-Json -Depth 12
} catch {
    $exception=$_.Exception
    while ($exception -isnot [ComponentModel.Win32Exception] -and $null -ne $exception.InnerException) {
        $exception=$exception.InnerException
    }
    $nativeError=if ($exception -is [ComponentModel.Win32Exception]) {
        @{code=$exception.NativeErrorCode;operation=$exception.Data['operation']
            source=$exception.Data['source'];destination=$exception.Data['destination']}
    } else { $null }
    @{status=$(if ($MockOnly) {'mock_failed'} else {'native_failed_or_unsupported_do_not_apply'})
        nativeExecuted=(-not $MockOnly);cases=$results;error=$_.Exception.Message
        selectedCase=$CaseName;failedCase=$script:activeCase;nativeError=$nativeError
        location=$_.ScriptStackTrace} | ConvertTo-Json -Depth 12
    exit 1
}
