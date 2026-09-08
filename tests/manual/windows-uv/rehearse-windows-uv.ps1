#requires -Version 7.6
[CmdletBinding()]
param([switch]$MockOnly,[string]$NativeRoot)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$results=[Collections.Generic.List[object]]::new()
foreach ($file in @('uv-state.ps1','windows-uv.ps1','rehearse-windows-uv.ps1','run-native-fixture.ps1')) {
    $tokens=$null; $errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $file),[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
    $results.Add(@{case="parser:$file"; status='passed'})
}
. (Join-Path $PSScriptRoot 'uv-state.ps1')
if (-not (Get-Command New-ExclusiveDirectory -CommandType Function -ErrorAction SilentlyContinue)) {
    throw 'New-ExclusiveDirectory must be defined at script scope before any caller or mock runs.'
}
$results.Add(@{case='function-export:New-ExclusiveDirectory';status='passed';kind='definition_not_native'})
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'windows-uv.ps1'),[ref]$tokens,[ref]$errors)
foreach ($function in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)) {
    if ($function.Name -in @('Get-CurrentStates','Complete-Pending','Publish-One','Test-Absent')) {
        . ([scriptblock]::Create($function.Extent.Text))
    }
}
if (-not $MockOnly) {
    if (-not $IsWindows) {
        @{status='unsupported_os_not_executed';parser=$results;nativeExecuted=$false} | ConvertTo-Json -Depth 10
        exit 2
    }
    Assert-Native
    Assert-Path $NativeRoot -Absent
    if (Test-Path -LiteralPath $NativeRoot) { throw 'NativeRoot must not exist; never reuse an existing fixture.' }
    Assert-Beneath $NativeRoot ([Environment]::GetFolderPath('UserProfile'))
    if ([IO.DriveInfo]::new([IO.Path]::GetPathRoot($NativeRoot)).DriveFormat -ne 'NTFS') { throw 'NTFS required.' }
    $null=[IO.Directory]::CreateDirectory($NativeRoot)
    $Backup=Join-Path $NativeRoot 'backup'
    $null=[IO.Directory]::CreateDirectory($Backup)
    $null=[IO.Directory]::CreateDirectory((Join-Path $Backup 'original'))
    $live=Join-Path $NativeRoot 'uv'
    $blob=Join-Path $Backup 'after'
    $null=[IO.Directory]::CreateDirectory((Join-Path $live 'nested'))
    [IO.File]::WriteAllText((Join-Path $live 'nested\uv.exe'),'old fixture, never executed')
    $null=[IO.Directory]::CreateDirectory($blob)
    [IO.File]::WriteAllText((Join-Path $blob 'uv.exe'),'new fixture, never executed')
    function Save-Journal($Journal) {
        Write-NewJson (Join-Path $Backup ('journal-observation-' + [guid]::NewGuid().ToString('N') + '.json')) $Journal
    }
    function Native-Check([string]$Name,[scriptblock]$Body) {
        & $Body
        $results.Add(@{case=$Name;status='passed';kind='native_fixture_not_install'})
    }
    function Native-Refusal([scriptblock]$Body) {
        $failed=$false; try { & $Body | Out-Null } catch { $failed=$true }
        if (-not $failed) { throw 'Expected native refusal.' }
    }
    try {
        $old=Read-Tree $live; $after=Read-Tree $blob
        $original=Join-Path $Backup 'original\0'
        Native-Check 'directory snapshot with nested file, ACL, attributes and timestamps' {
            Copy-Tree $live $original $old
        }
        Native-Check 'file snapshot' {
            $file=Join-Path $blob 'uv.exe'
            Copy-Tree $file (Join-Path $Backup 'single-file') (Read-Tree $file)
        }
        $state=@{entries=@(@{target=$live;saved='original\0';original=$old;after=$after})}
        $plan=@{entries=@(@{blob=$blob;after=$after})}
        $journal=@{phase='installed';pending=$null}
        Native-Check 'directory publish and repeated apply no-op' {
            $null=Get-CurrentStates $state $plan $journal
            Publish-One $state $journal 0 $blob $after
            Publish-One $state $journal 0 $blob $after
            Assert-Equal (Read-Tree $live) $after 'native after'
        }
        Native-Check 'restore without external candidate and repeat restore' {
            Publish-One $state $journal 0 $original $old
            Publish-One $state $journal 0 $original $old
            Assert-Equal (Read-Tree $live) $old 'native restore'
        }
        Native-Check 'interrupted after evacuation, then resume and offline restore' {
            $nonce=[guid]::NewGuid().ToString('N')
            $stage=Join-Path $NativeRoot ('.n4-uv-stage-' + $nonce)
            $quarantine=Join-Path $Backup ('evacuated-' + $nonce)
            Copy-Tree $blob $stage $after
            $journal.pending=@{index=0;before=$old;desired=$after;stage=$stage;quarantine=$quarantine}
            Save-Journal $journal
            Move-Tree $live $quarantine $old
            $null=Get-CurrentStates $state $plan $journal
            Complete-Pending $state $journal
            Publish-One $state $journal 0 $original $old
            Assert-Equal (Read-Tree $live) $old 'native interrupted restore'
        }
        Native-Check 'unknown content rejected before publish' {
            $path=Join-Path $live 'nested\uv.exe'
            [IO.File]::WriteAllText($path,'concurrent fixture change')
            Native-Refusal { Get-CurrentStates $state $plan $journal }
        }
        Native-Check 'readonly rejection without clearing managed attributes' {
            $path=Join-Path $NativeRoot 'readonly-fixture'
            [IO.File]::WriteAllText($path,'fixture')
            [IO.File]::SetAttributes($path,[IO.FileAttributes]::ReadOnly)
            Native-Refusal { Read-Tree $path }
        }
        Native-Check 'junction rejection before traversing' {
            $path=Join-Path $NativeRoot 'junction-fixture'
            $null=New-Item -ItemType Junction -Path $path -Target $blob
            Native-Refusal { Read-Tree $path }
        }
        Native-Check 'hardlink rejection' {
            $path=Join-Path $NativeRoot 'hardlink-source'
            [IO.File]::WriteAllText($path,'fixture')
            $null=New-Item -ItemType HardLink -Path (Join-Path $NativeRoot 'hardlink-alias') -Target $path
            Native-Refusal { Read-Tree $path }
        }
        Native-Check 'alternate data stream rejection' {
            $path=Join-Path $NativeRoot 'ads-fixture'
            [IO.File]::WriteAllText($path,'fixture')
            Set-Content -LiteralPath $path -Stream 'n4-test' -Value 'fixture stream'
            Native-Refusal { Read-Tree $path }
        }
        Native-Check 'original absence restored without deletion of unknown content' {
            $path=Join-Path $NativeRoot 'originally-absent'
            $absent=Read-Tree $path
            $s=@{entries=@(@{target=$path;original=$absent;after=$after})}
            $j=@{phase='installed';pending=$null}
            Publish-One $s $j 0 $blob $after
            Publish-One $s $j 0 (Join-Path $Backup 'absent-blob') $absent
            Assert-Equal (Read-Tree $path) $absent 'absent restore'
        }
        @{status='native_fixture_passed_not_install';nativeExecuted=$true;cases=$results;root=$NativeRoot
            note='Fixtures deliberately preserved. This does not validate mise, ARM64 emulation, real shims, or sandbox.'} |
            ConvertTo-Json -Depth 12
    } catch {
        @{status='native_failed_or_unsupported_do_not_apply';nativeExecuted=$true;cases=$results;root=$NativeRoot
            error=$_.Exception.Message} | ConvertTo-Json -Depth 12
        exit 1
    }
    exit 0
}
$Backup='/mock/backup'
$script:files=@{}
$script:failure=''
$script:moves=0
function Read-Tree([string]$Path) {
    if ($script:files.ContainsKey($Path)) { return (Get-Json $script:files[$Path] | ConvertFrom-Json -AsHashtable) }
    return @{kind='absent';nodes=@()}
}
function Copy-Tree([string]$Source,[string]$Destination,$Expected) {
    Assert-Equal (Read-Tree $Source) $Expected 'mock source changed'
    if ((Read-Tree $Destination).kind -ne 'absent') { throw 'mock destination occupied' }
    if ($Expected.kind -ne 'absent') { $script:files[$Destination]=$Expected }
}
function Move-Tree([string]$Source,[string]$Destination,$Expected) {
    Assert-Equal (Read-Tree $Source) $Expected 'mock source changed'
    if ((Read-Tree $Destination).kind -ne 'absent') { throw 'mock destination occupied' }
    if ($script:failure -eq 'before-evacuation') { $script:failure=''; throw 'injected before evacuation' }
    $script:files[$Destination]=$Expected
    $null=$script:files.Remove($Source)
    $script:moves++
    if ($script:failure -eq 'after-evacuation') { $script:failure=''; throw 'injected after evacuation' }
}
function Save-Journal($Journal) { $script:lastJournal=Get-Json $Journal }
function Check([string]$Name,[scriptblock]$Body) {
    & $Body
    $results.Add(@{case=$Name;status='passed';kind='mock_not_native'})
}
function Must-Fail([scriptblock]$Body) {
    $failed=$false
    try { & $Body | Out-Null } catch { $failed=$true }
    if (-not $failed) { throw 'Expected refusal' }
}
function Fixture([switch]$Absent) {
    $script:files=@{}; $script:moves=0; $script:failure=''
    $old=@{kind='directory';nodes=@(@{relative='';kind='directory';sddl='owner:DACL';attributes=16;created=1;written=1},
        @{relative='uv.exe';kind='file';hash='old-executable';sddl='owner:DACL';attributes=32;created=1;written=1})}
    if ($Absent) { $old=@{kind='absent';nodes=@()} }
    $new=@{kind='file';nodes=@(@{relative='';kind='file';hash='new-executable';sddl='owner:DACL';attributes=32;created=1;written=1})}
    $script:files['/mock/live/uv']=$old
    $script:files['/mock/backup/original/0']=$old
    $script:files['/mock/backup/prepared/0']=$new
    @{
        state=@{entries=@(@{target='/mock/live/uv';saved='original/0';original=$old;after=$new})}
        plan=@{entries=@(@{blob='/mock/backup/prepared/0';after=$new})}
        journal=@{phase='installed';pending=$null}; old=$old; new=$new
    }
}
Check 'stable comparison ignores dictionary key order, not values' {
    Assert-Equal @{b=2;a=1} @{a=1;b=2} 'ordering'
    Must-Fail { Assert-Equal @{a=1} @{a=2} 'different' }
}
Check 'file, directory, absence are distinct' {
    $f=Fixture
    Must-Fail { Assert-Known @{kind='absent';nodes=@()} $f.old $f.new }
    Assert-Equal (Assert-Known $f.old $f.old $f.new) 'original' 'old'
    Assert-Equal (Assert-Known $f.new $f.old $f.new) 'after' 'new'
}
foreach ($field in @('hash','sddl','attributes','created','written')) {
    Check "unknown $field refuses" {
        $f=Fixture
        $changed=Get-Json $f.new | ConvertFrom-Json -AsHashtable
        $changed.nodes[0][$field]='unknown'
        Must-Fail { Assert-Known $changed $f.old $f.new }
    }
}
Check 'all-target preflight refuses later conflict before first write' {
    $f=Fixture
    $f.state.entries+=@{target='/mock/live/second';saved='original/1';original=$f.old}
    $f.plan.entries+=@{blob='/mock/backup/prepared/1';after=$f.new}
    $script:files['/mock/live/second']=@{kind='file';nodes=@(@{hash='concurrent'})}
    Must-Fail { Get-CurrentStates $f.state $f.plan $f.journal }
    Assert-Equal $script:moves 0 'Must not mutate first target'
}
Check 'apply and offline restore preserve directory tree; second restore no-op' {
    $f=Fixture
    $null=Get-CurrentStates $f.state $f.plan $f.journal
    Publish-One $f.state $f.journal 0 '/mock/backup/prepared/0' $f.new
    $null=$script:files.Remove('/mock/backup/prepared/0')
    $null=Get-CurrentStates $f.state $f.plan $f.journal
    Publish-One $f.state $f.journal 0 '/mock/backup/original/0' $f.old
    Assert-Equal (Read-Tree '/mock/live/uv') $f.old 'offline original'
    $moves=$script:moves
    Publish-One $f.state $f.journal 0 '/mock/backup/original/0' $f.old
    Assert-Equal $script:moves $moves 'restore no-op'
}
Check 'absent cache restored by evacuation, not recursive deletion' {
    $f=Fixture -Absent
    Publish-One $f.state $f.journal 0 '/mock/backup/prepared/0' $f.new
    Publish-One $f.state $f.journal 0 '/mock/backup/original/0' $f.old
    Assert-Equal (Read-Tree '/mock/live/uv').kind 'absent' 'absence'
}
foreach ($point in @('before-evacuation','after-evacuation')) {
    Check "interruption $point resumes then restores without installer/network" {
        $f=Fixture; $script:failure=$point
        Must-Fail { Publish-One $f.state $f.journal 0 '/mock/backup/prepared/0' $f.new }
        $null=Get-CurrentStates $f.state $f.plan $f.journal
        Complete-Pending $f.state $f.journal
        Publish-One $f.state $f.journal 0 '/mock/backup/original/0' $f.old
        Assert-Equal (Read-Tree '/mock/live/uv') $f.old 'restoration'
    }
}
Check 'unknown quarantined bytes after interruption refuses' {
    $f=Fixture; $script:failure='after-evacuation'
    Must-Fail { Publish-One $f.state $f.journal 0 '/mock/backup/prepared/0' $f.new }
    $script:files[$f.journal.pending.quarantine]=$f.new
    Must-Fail { Get-CurrentStates $f.state $f.plan $f.journal }
}
Check 'unknown target after interruption refuses' {
    $f=Fixture; $script:failure='after-evacuation'
    Must-Fail { Publish-One $f.state $f.journal 0 '/mock/backup/prepared/0' $f.new }
    $script:files['/mock/live/uv']=@{kind='file';nodes=@(@{hash='concurrent'})}
    Must-Fail { Get-CurrentStates $f.state $f.plan $f.journal }
}
Check 'damaged backup stops copy before target move' {
    $f=Fixture
    $script:files['/mock/backup/prepared/0']=$f.old
    Must-Fail { Publish-One $f.state $f.journal 0 '/mock/backup/prepared/0' $f.new }
    Assert-Equal $script:moves 0 'No evacuation'
}
Check 'unknown target between preflight and publish is not adopted as before' {
    $f=Fixture
    $null=Get-CurrentStates $f.state $f.plan $f.journal
    $script:files['/mock/live/uv']=@{kind='file';nodes=@(@{hash='concurrent'})}
    Must-Fail { Publish-One $f.state $f.journal 0 '/mock/backup/prepared/0' $f.new }
    Assert-Equal $script:moves 0 'Do not adopt unknown live state'
}
Check 'pending journal cannot introduce an unknown desired state' {
    $f=Fixture; $script:failure='after-evacuation'
    Must-Fail { Publish-One $f.state $f.journal 0 '/mock/backup/prepared/0' $f.new }
    $f.journal.pending.desired=@{kind='file';nodes=@(@{hash='unsealed'})}
    Must-Fail { Get-CurrentStates $f.state $f.plan $f.journal }
}
Check 'pending journal cannot redirect quarantine outside backup' {
    $f=Fixture; $script:failure='after-evacuation'
    Must-Fail { Publish-One $f.state $f.journal 0 '/mock/backup/prepared/0' $f.new }
    $f.journal.pending.quarantine='/mock/unrelated-object'
    Must-Fail { Get-CurrentStates $f.state $f.plan $f.journal }
}
Check 'failed isolated install needs no live restoration' {
    $f=Fixture
    $null=$script:files.Remove('/mock/backup/prepared/0')
    $null=Get-CurrentStates $f.state $null $f.journal
    Publish-One $f.state $f.journal 0 '/mock/backup/original/0' $f.old
    Assert-Equal $script:moves 0 'Original live install untouched'
}
@{status='mock_passed';nativeExecuted=$false;cases=$results;count=$results.Count
    scope='Parser and in-memory state transitions only. No Windows API, ACL, installer or actual HOME operations.'} |
    ConvertTo-Json -Depth 12
