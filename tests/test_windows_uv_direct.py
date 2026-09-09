"""直接移行の合成試験。ネイティブ操作と導入プロセスはmockへ置き換える。"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

from test_windows_uv_source import PWSH, ROOT


ENTRY = ROOT / "tests/manual/windows-uv/direct-windows-uv.ps1"
HARNESS = r"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$script:fixtureScriptRoot=$env:TEST_ENTRY
foreach ($name in @('uv-state.ps1','plan-direct-windows-uv.ps1','direct-windows-uv.ps1')) {
    $tokens=$null; $errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $env:TEST_ENTRY $name),[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
    foreach ($node in $ast.FindAll({
        param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]
    },$false)) { . ([scriptblock]::Create($node.Extent.Text.Replace('$PSScriptRoot','$script:fixtureScriptRoot'))) }
}
if ($env:TEST_MODE -eq 'toml-roundtrip') {
    $value=Read-Json (Join-Path $env:TEST_ROOT 'input.json')
    $text=ConvertTo-DirectToml $value $env:TEST_CHEZMOI $env:TEST_ROOT
    $parsed=ConvertFrom-Toml $text $env:TEST_CHEZMOI $env:TEST_ROOT
    Assert-Equal $parsed $value 'Real chezmoi TOML round-trip changed semantics.'
    @{accepted=$true} | ConvertTo-Json -Compress
    exit 0
}
$script:ids=@{}
$script:nextId=0
$script:restoring=$false
$script:copyCrashed=$false
function Write-DirectBytes([string]$Path, [byte[]]$Bytes) {
    $stream=[IO.FileStream]::new($Path,'CreateNew','Write','None')
    try {
        if ($env:TEST_MODE -like 'copy-crash*' -and -not $script:copyCrashed) {
            $script:copyCrashed=$true
            $stream.Write($Bytes,0,[Math]::Max(1,[int]($Bytes.Length/2)))
            $stream.Flush($true)
            throw 'Synthetic interruption during metadata copy.'
        }
        $stream.Write($Bytes); $stream.Flush($true)
    } finally { $stream.Dispose() }
}
function Get-FixtureId($Path) {
    if (-not $script:ids.ContainsKey($Path)) { $script:ids[$Path]=++$script:nextId }
    $script:ids[$Path]
}
function Read-Tree([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return @{kind='absent';nodes=@()} }
    $nodes=@()
    $items=@(Get-Item -LiteralPath $Path -Force)
    if ($items[0].PSIsContainer) { $items+=@(Get-ChildItem -LiteralPath $Path -Recurse -Force | Sort-Object FullName) }
    foreach ($item in $items) {
        $relative=if ($item.FullName -eq $Path) {''} else {$item.FullName.Substring($Path.Length+1)}
        $nodes+=@{relative=$relative;identity=(Get-FixtureId $item.FullName)
            kind=$(if ($item.PSIsContainer) {'directory'} else {'file'})
            hash=$(if (-not $item.PSIsContainer) {Get-Hash $item.FullName})}
    }
    @{kind=$nodes[0].kind;nodes=$nodes}
}
function Read-Parent([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw 'Missing parent.' }
    @{kind='directory';identity=(Get-FixtureId $Path)}
}
function New-ExclusiveDirectory([string]$Path) {
    if (Test-Path -LiteralPath $Path) { throw 'Directory exists.' }
    $null=[IO.Directory]::CreateDirectory($Path)
}
function Move-Tree([string]$Source,[string]$Destination,$Expected) {
    Assert-Equal (Read-Tree $Source) $Expected 'Mock source changed.'
    if (Test-Path -LiteralPath $Destination) { throw 'Mock overwrite forbidden.' }
    $keys=@($script:ids.Keys | Where-Object { $_ -eq $Source -or $_.StartsWith($Source+'/') })
    foreach ($key in $keys) {
        $script:ids[$Destination+$key.Substring($Source.Length)]=$script:ids[$key]
        $script:ids.Remove($key)
    }
    if ($Expected.kind -eq 'directory') { [IO.Directory]::Move($Source,$Destination) }
    else { [IO.File]::Move($Source,$Destination) }
    if ($env:TEST_MODE -eq 'rename-crash' -and -not $script:crashed) {
        $script:crashed=$true; throw 'Synthetic interruption after native rename.'
    }
    if ($env:TEST_MODE -eq 'installer-crash-restore-crash' -and $script:restoring -and -not $script:crashed) {
        $script:crashed=$true; throw 'Synthetic interruption during quarantine rename.'
    }
    Assert-Equal (Read-Tree $Destination) $Expected 'Mock identity mismatch.'
}
function ConvertFrom-Toml([string]$Text) { $Text | ConvertFrom-Json -AsHashtable }
function Put($Path,$Text) {
    $null=[IO.Directory]::CreateDirectory((Split-Path $Path))
    [IO.File]::WriteAllText($Path,$Text)
}
function Assert-DirectEnvironment {}
function Assert-Path {}
$script:crashed=$false
$script:installCalls=0
function Invoke-DirectChild($State,$Executable,$Arguments) {
    if ($Arguments[0] -eq '--version') {
        $text=if ($Executable -eq $State.mise) {'2026.8.5 windows-x64'} else {
            (Split-Path $Executable -LeafBase)+' 0.12.10'
        }
        return @{exitCode=0;stdout=$text;stderr=''}
    }
    $canonical=(Get-DirectEntry $State 'version').target
    if ($Arguments[0] -eq 'which') {
        return @{exitCode=0;stdout=(Join-Path $canonical ($Arguments[1]+'.exe'));stderr=''}
    }
    Assert-Equal $Arguments @('install','--locked','uv') 'Not an official direct install invocation.'
    $script:installCalls++
    if (Test-Path $canonical) { throw 'Canonical destination was not vacant.' }
    foreach ($name in @('uv','uvx')) { Put (Join-Path $canonical "$name.exe") "official-$name" }
    if ($env:TEST_MODE -like 'installer-crash*') { throw 'Synthetic loss of process outcome.' }
    if ($env:TEST_MODE -eq 'installer-fail') { return @{exitCode=9;stdout='private output';stderr='private failure'} }
    $installs=Join-Path $State.roots.data 'installs'
    $manifest=Read-Json (Join-Path $installs '.mise-installs.toml')
    $manifest.uv=@{short='uv';full='github:astral-sh/uv';explicit_backend=$false
        opts=@{platforms=@{'windows-arm64'=@{asset_pattern='uv-x86_64-pc-windows-msvc.zip'}}}}
    Put (Join-Path $installs '.mise-installs.toml') (Get-Json $manifest)
    Put (Join-Path $installs 'uv/.mise.backend.toml') (Get-Json $manifest.uv)
    foreach ($name in @('0','0.11','0.12','latest')) {
        Put (Join-Path $installs "uv/$name") $(if ($name -eq '0.11') {'.\0.11.31'} else {'.\0.12.10'})
    }
    if ($env:TEST_MODE -eq 'legacy-delete') {
        # 想定外の移行がmetadataコピーを削除しても、保存した元オブジェクトは残る。
        [IO.File]::Delete((Join-Path $installs 'tool00/.mise.backend.toml'))
    }
    Put (Join-Path $State.recovery 'work/cache/uv/0.12.10/metadata') 'official-cache'
    return @{exitCode=0;stdout='private success';stderr=''}
}
try {
    if ($env:TEST_MODE -eq 'hash') {
        Assert-DirectHash (Join-Path $env:TEST_ROOT 'input') ('0'*64)
        throw 'Hash check unexpectedly accepted.'
    }
    if ($env:TEST_MODE -eq 'nested-recovery') {
        Put (Join-Path $env:TEST_ROOT 'direct-snapshot.json') '{"phase":"restored"}'
        Assert-DirectFreshRecoveryParent (Join-Path $env:TEST_ROOT 'nested')
        throw 'Nested recovery was unexpectedly accepted.'
    }
    if ($env:TEST_MODE -like 'source-*') {
        $inputs=@{}
        foreach ($relative in @('home\dot_config\mise\config.toml.tmpl','home\dot_config\mise\private_mise.lock')) {
            $path=Join-Path $env:TEST_ROOT $relative
            Put $path 'pinned input'
            $inputs["C:\old-inventory-source\$relative"]=@{nodes=@(@{hash=(Get-Hash $path)})}
        }
        if ($env:TEST_MODE -eq 'source-mismatch') { Put (Join-Path $env:TEST_ROOT 'home/dot_config/mise/private_mise.lock') 'unapproved' }
        Assert-DirectSourceInputs $env:TEST_ROOT $inputs
        @{accepted=$true} | ConvertTo-Json -Compress
        exit 0
    }
    $root=$env:TEST_ROOT
    $recovery=Join-Path $root 'recovery'
    foreach ($dir in @('originals','events','quarantine','publish','work/config','work/cache','work/system',
            'work/state','work/shims','work/plugins','work/temp')) {
        $null=[IO.Directory]::CreateDirectory((Join-Path $recovery $dir))
    }
    $data=Join-Path $root 'data'; $cache=Join-Path $root 'cache'
    $installs=Join-Path $data 'installs'
    $config=Join-Path $root 'config/config.toml'
    Put $config 'original-config'; Put (Join-Path $root 'config/mise.lock') 'original-lock'
    Put (Join-Path $cache 'uv/old-cache') 'original-cache'
    Put (Join-Path $data 'downloads/uv/old-download') 'original-download'
    $versions=@('0.11.29','0.11.31','0.12.0','0.12.10','0.12.2','0.12.5','0.12.7','0.12.8','0.12.9')
    foreach ($v in $versions) { Put (Join-Path $installs "uv/$v/uv.exe") "original-$v" }
    Put (Join-Path $installs 'uv/0.12.10/uvx.exe') 'original-uvx'
    foreach ($n in 0..3) { Put (Join-Path $installs "uv/.n4-evidence-$n/retained") 'untouched evidence' }
    foreach ($name in @('0','0.11','0.12','latest')) {
        Put (Join-Path $installs "uv/$name") $(if ($name -eq '0.11') {'.\0.11.31'} else {'.\0.12.10'})
    }
    $metadata=@{}; $shared=@{}
    $shared.uv=@{short='uv';full='aqua:astral-sh/uv';explicit_backend=$false}
    for ($i=0;$i -lt 40;$i++) {
        $name='tool{0:D2}' -f $i
        $shared[$name]=@{short=$name;full="core:$name";explicit_backend=$true}
        $null=[IO.Directory]::CreateDirectory((Join-Path $installs $name))
        if ($i -lt 27) {
            $path=Join-Path $installs "$name/.mise.backend.toml"
            $metadata[$path]=$shared[$name]; Put $path (Get-Json $shared[$name])
        }
    }
    $metadata[(Join-Path $installs '.mise-installs.toml')]=$shared
    $metadata[(Join-Path $installs 'uv/.mise.backend.toml')]=$shared.uv
    Put (Join-Path $installs '.mise-installs.toml') (Get-Json $shared)
    Put (Join-Path $installs 'uv/.mise.backend.toml') (Get-Json $shared.uv)
    $inventory=Get-DirectInventory $installs $cache (Join-Path $data 'downloads') @{}
    Assert-DirectPointers $inventory
    if ($env:TEST_MODE -eq 'metadata-unknown') {
        $metadata[(Join-Path $installs 'tool00/.mise.backend.toml')]=@{short='tool00';full='core:tool00';explicit_backend=$true;unknown='field'}
    }
    if ($env:TEST_MODE -eq 'metadata-distinct') {
        # 共有側のoptsと、上流が優先する個別TOMLの両方を元の意味のまま保持する。
        $shared.tool00=@{short='tool00';full='core:other';explicit_backend=$false;opts=@{setting=@('value')}}
        Put (Join-Path $installs '.mise-installs.toml') (Get-Json $shared)
    }
    if ($env:TEST_MODE -eq 'metadata-brackets') { $shared.tool00.full='core:tool00[option=value]' }
    Assert-DirectMetadata $metadata $inventory $installs
    $targets=@(
        @('version',(Join-Path $installs 'uv/0.12.10')),
        @('manifest',(Join-Path $installs '.mise-installs.toml')),
        @('backend',(Join-Path $installs 'uv/.mise.backend.toml')),
        @('cache',(Join-Path $cache 'uv')),
        @('downloads',(Join-Path $data 'downloads/uv')),
        @('config',$config),@('lock',(Join-Path $root 'config/mise.lock'))
    )
    foreach ($name in @('0','0.11','0.12','latest')) { $targets+=,@('pointer',(Join-Path $installs "uv/$name")) }
    for ($i=0;$i -lt 27;$i++) { $targets+=,@('legacy',(Join-Path $installs ('tool{0:D2}/.mise.backend.toml' -f $i))) }
    $entries=@(); $current=@{}; $saved=@{}; $parents=@{}; $guards=@{}
    foreach ($target in $targets) {
        $id='{0:D3}' -f $entries.Count
        $tree=Read-Tree $target[1]
        $entries+=@{id=$id;role=$target[0];target=$target[1];original=$tree;saved="originals/$id"}
        $current[$target[1]]=$tree; $saved[$target[1]]=$false
        $parent=Split-Path $target[1]; $parents[$parent]=Read-Parent $parent
    }
    foreach ($v in $versions | Where-Object {$_ -ne '0.12.10'}) {
        $path=Join-Path $installs "uv/$v"; $guards[$path]=Read-Tree $path
    }
    foreach ($n in 0..3) {
        $path=Join-Path $installs "uv/.n4-evidence-$n"; $guards[$path]=Read-Tree $path
    }
    Put (Join-Path $recovery 'publish/config.toml') 'candidate-config'
    Put (Join-Path $recovery 'publish/mise.lock') 'candidate-lock'
    $state=@{digest=('A'*64);recovery=$recovery;roots=@{data=$data;cache=$cache;config=$config}
        entries=$entries;guards=$guards;parents=$parents;sealed=@{};toolHashes=@{};mise='mock-mise';chezmoi='mock-chezmoi'
        uvNames=@($versions)+@('0','0.11','0.12','latest','.mise.backend.toml')+@(0..3 | ForEach-Object {".n4-evidence-$_"})
        outsideScopeNames=@(0..3 | ForEach-Object {".n4-evidence-$_"})
        installNames=@(Get-ChildItem -LiteralPath $installs -Directory | ForEach-Object Name | Sort-Object)
        metadata=$metadata
        publication=@{config=(Read-Tree (Join-Path $recovery 'publish/config.toml'));lock=(Read-Tree (Join-Path $recovery 'publish/mise.lock'))}
    }
    $journal=@{sequence=0;previous=$state.digest;phase='prepared';pending=$null;current=$current;saved=$saved}
    if ($env:TEST_MODE -eq 'prepare-success') {
        $Source=Join-Path $root 'source'; $SourceCommit='a'*40
        $candidateLock=Read-Json (Join-Path $root 'input.json')
        $oldLock=Get-Json $candidateLock | ConvertFrom-Json -AsHashtable
        foreach ($entry in $oldLock.tools.uv) { $entry.backend='aqua:astral-sh/uv' }
        $configuration=@{tools=@{};settings=@{experimental=$true;lockfile=$true}}
        foreach ($name in $oldLock.tools.Keys) { $configuration.tools[$name]='latest' }
        Put $config (Get-Json $configuration)
        $lock=Join-Path (Split-Path $config) 'mise.lock'; Put $lock (Get-Json $oldLock)
        $sourceInputs=@{}
        foreach ($name in @('direct-windows-uv.ps1','plan-direct-windows-uv.ps1','uv-state.ps1')) {
            Put (Join-Path $Source "tests/manual/windows-uv/$name") ([IO.File]::ReadAllText((Join-Path $env:TEST_ENTRY $name)))
        }
        foreach ($relative in @('home\dot_config\mise\config.toml.tmpl','home\dot_config\mise\private_mise.lock')) {
            $path=Join-Path $Source $relative
            Put $path $(if ($relative.EndsWith('private_mise.lock')) {Get-Json $candidateLock} else {'template fixture'})
            $sourceInputs["C:\old-source\$relative"]=Read-Tree $path
        }
        $sourceInputs[$config]=Read-Tree $config; $sourceInputs[$lock]=Read-Tree $lock
        $script:fixtureMise=Join-Path $root 'mise.exe'; Put $script:fixtureMise 'mise fixture'
        $script:fixtureChezmoi=Join-Path $root 'chezmoi.exe'; Put $script:fixtureChezmoi 'chezmoi fixture'
        function Get-Command($Name) { @{Source=$(if ($Name -eq 'mise') {$script:fixtureMise} else {$script:fixtureChezmoi})} }
        function Assert-DirectSource {}
        function ConvertTo-DirectToml($Value) { Get-Json $Value }
        $Recovery=Join-Path $root 'prepared-recovery'
        $Report=Join-Path $root 'inventory.json'
        $declaration=@{version='latest';platforms=@{'windows-arm64'=@{asset_pattern='uv-x86_64-pc-windows-msvc.zip'}}}
        $reportValue=@{
            format='windows-uv-direct-inventory';schema=1;expectedVersion='0.12.10'
            canApply=$false;installerInvoked=$false;originalsMoved=$false;sourceCommit=('b'*40)
            roots=@{config=$config;data=$data;cache=$cache;recovery=$Recovery}
            parents=@{};inputs=$sourceInputs;inventory=$inventory;metadata=$metadata
            toolHashes=@{$script:fixtureMise=(Get-Hash $script:fixtureMise);$script:fixtureChezmoi=(Get-Hash $script:fixtureChezmoi)}
            proposedConfigDigest=(Get-DirectDigest (Get-DirectCandidateConfig $configuration $declaration))
            proposedLockDigest=(Get-DirectDigest (Assert-DirectLock $oldLock $candidateLock '0.12.10'))
        }
        Write-NewJson $Report $reportValue; $ReportDigest=Get-Hash $Report
        $state=Initialize-DirectRecovery
        $recovery=$Recovery
        $journal=Read-DirectJournal $state
    } else { Save-DirectEvent $state $journal }
    $failure=''
    try { Install-Direct $state $journal } catch { $failure=$_.Exception.Message + "`n" + $_.ScriptStackTrace }
    $phase=$journal.phase
    $marker=Test-Path (Join-Path $cache 'uv/0.12.10/incomplete')
    if ($env:TEST_MODE -eq 'success' -and $failure) { throw "Unexpected install failure: $failure" }
    if ($env:TEST_MODE -eq 'unexpected') { Put (Join-Path $installs 'uv/0.12.2/uv.exe') 'external edit' }
    if ($env:TEST_MODE -eq 'legacy-tamper') {
        Put (Join-Path $recovery 'originals/011') 'external backup edit'
    }
    if ($env:TEST_MODE -eq 'installer-crash-backup-tamper') {
        Put (Join-Path $recovery 'originals/000/uv.exe') 'external original edit'
    }
    if ($env:TEST_MODE -eq 'installer-crash-config-tamper') { Put $config 'external config edit' }
    if ($env:TEST_MODE -eq 'installer-crash-unknown-file') {
        Put (Join-Path $installs 'uv/0.12.10/unknown.txt') 'retain without claiming installer provenance'
    }
    if ($env:TEST_MODE -eq 'journal-tamper') {
        $path=Join-Path $recovery 'events/000001.json'
        $old=Read-Json $path; $old.phase='edited'; Put $path (Get-Json $old)
    }
    $journal=Read-DirectJournal $state
    $restoreFailure=''
    $allowInterrupted=$env:TEST_MODE -like 'installer-crash-*' -or $env:TEST_MODE -eq 'copy-crash-restore'
    $script:restoring=$true
    try { Restore-Direct $state $journal -QuarantineInterruptedOutputs:$allowInterrupted }
    catch { $restoreFailure=$_.Exception.Message + "`n" + $_.ScriptStackTrace }
    if ($env:TEST_MODE -eq 'installer-crash-restore-crash') {
        if ($restoreFailure -notlike '*Synthetic interruption during quarantine rename*') { throw 'Expected quarantine interruption.' }
        $journal=Read-DirectJournal $state
        Restore-Direct $state $journal
        $restoreFailure=''
    }
    if ($env:TEST_MODE -in @('success','installer-fail','rename-crash','legacy-delete') -and $restoreFailure) {
        throw "Unexpected restore failure: $restoreFailure"
    }
    $retained=@(Get-ChildItem (Join-Path $recovery 'quarantine')).Count
    $unknown=@(Get-ChildItem -LiteralPath (Join-Path $recovery 'quarantine') -Recurse -File |
        Where-Object Name -CEQ 'unknown.txt')
    $disposition=if ($journal.ContainsKey('interruptedRestore')) { $journal.interruptedRestore.disposition } else { '' }
    @{phase=$phase;failure=$failure;restoreFailure=$restoreFailure;final=$journal.phase
        installerCalls=$script:installCalls;markerAfterInstall=$marker;retained=$retained
        sourceConfig=[IO.File]::ReadAllText($config);entries=$entries.Count
        disposition=$disposition;unknownRetained=@($unknown | ForEach-Object {[IO.File]::ReadAllText($_.FullName)})} | ConvertTo-Json -Compress
} catch {
    [Console]::Error.WriteLine($_.Exception.Message + "`n" + $_.ScriptStackTrace)
    exit 1
}
"""


@unittest.skipUnless(PWSH, "existing PowerShell required")
class WindowsUvDirectTests(unittest.TestCase):
    def test_plan_function_loader_keeps_explicit_source_directory(self):
        harness = r"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $env:TEST_ENTRY 'uv-state.ps1')
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $env:TEST_ENTRY 'plan-direct-windows-uv.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($node in $ast.FindAll({
    param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]
},$false)) {
    . ([scriptblock]::Create($node.Extent.Text))
}
function Assert-DirectEnvironment {}
function Assert-Path {}
function ConvertTo-DirectPath([string]$Path) { $Path }
function Invoke-Captured($Executable, $Arguments, $Directory) {
    if ($Arguments -contains '--show-toplevel') { return @{stdout=$env:TEST_SOURCE} }
    if ($Arguments -contains 'HEAD') { return @{stdout=('a'*40)} }
    if ($Arguments -contains 'status' -or $Arguments -contains 'ls-files') { return @{stdout=''} }
    throw 'Unexpected Git operation.'
}
Assert-DirectSource $env:TEST_SOURCE ('a'*40) $env:TEST_ENTRY
'source_verified'
"""
        result = subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", harness],
            cwd=ROOT, env=os.environ | {"TEST_ENTRY": str(ENTRY.parent), "TEST_SOURCE": str(ROOT)},
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "source_verified")

    def run_mode(self, mode, error=None, value=None):
        with tempfile.TemporaryDirectory(prefix=".windows-uv-transaction-", dir=ROOT) as directory:
            root = Path(directory)
            (root / "input").write_text("report or executable with an unapproved digest")
            if value is not None:
                (root / "input.json").write_text(json.dumps(value))
            result = subprocess.run(
                [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", HARNESS],
                cwd=root, env=os.environ | {
                    "TEST_ENTRY": str(ENTRY.parent), "TEST_ROOT": str(root), "TEST_MODE": mode,
                    "TEST_CHEZMOI": shutil.which("chezmoi") or "",
                }, capture_output=True, text=True, check=False,
            )
            if error:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                return
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_success_and_offline_identity_restore_all_scopes(self):
        result = self.run_mode("success")
        self.assertEqual(result["phase"], "installed")
        self.assertEqual(result["final"], "restored")
        self.assertEqual(result["installerCalls"], 1)
        self.assertEqual(result["sourceConfig"], "original-config")
        self.assertFalse(result["markerAfterInstall"])
        self.assertEqual(result["entries"], 38)
        self.assertGreater(result["retained"], 27)

    def test_prepare_install_restore_from_synthetic_original_report(self):
        lock = tomllib.loads((ROOT / "home/dot_config/mise/private_mise.lock").read_text())
        result = self.run_mode("prepare-success", value=lock)
        self.assertEqual(result["phase"], "installed", result["failure"])
        self.assertEqual(result["final"], "restored", result["restoreFailure"])
        self.assertEqual(json.loads(result["sourceConfig"])["tools"]["uv"], "latest")

    def test_installer_failure_remains_incomplete_until_explicit_restore(self):
        result = self.run_mode("installer-fail")
        self.assertEqual(result["phase"], "installer-exited")
        self.assertIn("Official install failed", result["failure"])
        self.assertTrue(result["markerAfterInstall"])
        self.assertEqual(result["final"], "restored")
        self.assertEqual(result["installerCalls"], 1)

    def test_interrupted_rename_resolves_by_original_identity(self):
        result = self.run_mode("rename-crash")
        self.assertEqual(result["final"], "restored")
        self.assertEqual(result["installerCalls"], 0)

    def test_unsealed_installer_crash_is_not_success_or_adopted(self):
        result = self.run_mode("installer-crash")
        self.assertEqual(result["phase"], "installer-started")
        self.assertTrue(result["markerAfterInstall"])
        self.assertIn("Unsealed", result["restoreFailure"])

    def test_interrupted_installer_can_quarantine_outputs_with_explicit_authorization(self):
        result = self.run_mode("installer-crash-restore")
        self.assertEqual(result["phase"], "installer-started")
        self.assertEqual(result["final"], "restored", result["restoreFailure"])
        self.assertEqual(result["installerCalls"], 1)
        self.assertEqual(result["disposition"], "quarantine_only_provenance_unknown")
        self.assertEqual(result["sourceConfig"], "original-config")

    def test_interrupted_copy_needs_authorization_and_can_then_restore_originals(self):
        blocked = self.run_mode("copy-crash")
        self.assertIn("Unsealed", blocked["restoreFailure"])
        result = self.run_mode("copy-crash-restore")
        self.assertEqual(result["final"], "restored", result["restoreFailure"])
        self.assertEqual(result["installerCalls"], 0)
        self.assertEqual(result["disposition"], "quarantine_only_provenance_unknown")

    def test_interrupted_restore_preserves_unknown_content_without_adopting_it(self):
        result = self.run_mode("installer-crash-unknown-file")
        self.assertEqual(result["final"], "restored", result["restoreFailure"])
        self.assertEqual(result["unknownRetained"], ["retain without claiming installer provenance"])
        self.assertEqual(result["disposition"], "quarantine_only_provenance_unknown")

    def test_interrupted_restore_cannot_accept_changes_to_originals_or_config(self):
        for mode, message in (
            ("installer-crash-backup-tamper", "Original backup changed"),
            ("installer-crash-config-tamper", "outside interrupted write scope"),
        ):
            with self.subTest(mode=mode):
                result = self.run_mode(mode)
                self.assertIn(message, result["restoreFailure"])
                self.assertNotEqual(result["final"], "restored")
                self.assertEqual(result["disposition"], "")

    def test_interruption_during_quarantine_rename_resumes_from_recorded_identity(self):
        result = self.run_mode("installer-crash-restore-crash")
        self.assertEqual(result["final"], "restored", result["restoreFailure"])
        self.assertEqual(result["installerCalls"], 1)

    def test_external_edit_to_retained_version_blocks_restore(self):
        result = self.run_mode("unexpected")
        self.assertIn("protected-object change", result["restoreFailure"])
        self.assertNotEqual(result["final"], "restored")

    def test_unexpected_legacy_deletion_restores_original_objects(self):
        result = self.run_mode("legacy-delete")
        self.assertNotEqual(result["failure"], "")
        self.assertEqual(result["final"], "restored")
        self.assertTrue(result["markerAfterInstall"])

    def test_digest_mismatch_is_fail_closed(self):
        self.run_mode("hash", "Input hash mismatch")

    def test_journal_tampering_is_detected_before_restore(self):
        self.run_mode("journal-tamper", "Broken journal digest chain")

    def test_unexpected_backup_slot_blocks_restore(self):
        result = self.run_mode("legacy-tamper")
        self.assertIn("Original backup changed", result["restoreFailure"])
        self.assertNotEqual(result["final"], "restored")

    def test_existing_direct_recovery_cannot_contain_a_new_migration(self):
        self.run_mode("nested-recovery", "existing direct recovery")

    @unittest.skipUnless(shutil.which("chezmoi"), "existing chezmoi required")
    def test_real_chezmoi_roundtrip_preserves_lock_and_private_config_semantics(self):
        lock = tomllib.loads((ROOT / "home/dot_config/mise/private_mise.lock").read_text())
        config = {
            "tools": {"uv": {"version": "latest", "platforms": {
                "windows-arm64": {"asset_pattern": "uv-x86_64-pc-windows-msvc.zip"},
            }}},
            "tool_alias": {"uv": "github:astral-sh/uv"},
            "settings": {"experimental": True, "lockfile": True},
        }
        for value in (lock, config, {}):
            with self.subTest(kind="empty" if not value else "lock" if "lockfile_version" in value else "config"):
                self.assertTrue(self.run_mode("toml-roundtrip", value=value)["accepted"])

    def test_revised_source_accepts_same_inputs_from_old_report(self):
        self.assertTrue(self.run_mode("source-new-commit")["accepted"])

    def test_revised_source_cannot_change_pinned_config_or_lock(self):
        self.run_mode("source-mismatch", "Input hash mismatch")

    def test_other_metadata_unknown_fields_and_implicit_option_migration_are_blocked(self):
        self.run_mode("metadata-unknown", "Unsupported manifest fields")
        self.run_mode("metadata-brackets", "Unsupported manifest meaning")

    def test_shared_options_and_distinct_per_tool_metadata_are_preserved_separately(self):
        result = self.run_mode("metadata-distinct")
        self.assertEqual(result["phase"], "installed", result["failure"])
        self.assertEqual(result["final"], "restored", result["restoreFailure"])

    def test_offline_bootstrap_rejects_recovery_and_script_tampering_before_native_calls(self):
        for corrupt_digest in (True, False):
            with self.subTest(corrupt_digest=corrupt_digest):
                with tempfile.TemporaryDirectory(prefix=".windows-uv-bootstrap-", dir=ROOT) as directory:
                    root = Path(directory)
                    scripts = {}
                    for name in ("direct-windows-uv.ps1", "plan-direct-windows-uv.ps1", "uv-state.ps1"):
                        data = (ENTRY.parent / name).read_bytes()
                        (root / name).write_bytes(data)
                        scripts[name] = hashlib.sha256(data).hexdigest().upper()
                    snapshot = json.dumps({
                        "format": "windows-uv-direct-recovery", "schema": 1, "scripts": scripts,
                    }).encode()
                    (root / "direct-snapshot.json").write_bytes(snapshot)
                    digest = "0" * 64 if corrupt_digest else hashlib.sha256(snapshot).hexdigest()
                    if not corrupt_digest:
                        (root / "uv-state.ps1").write_text("throw 'untrusted helper executed'")
                    result = subprocess.run(
                        [PWSH, "-NoProfile", "-NonInteractive", "-File", str(root / ENTRY.name),
                         "-Command", "Restore", "-Recovery", str(root), "-RecoveryDigest", digest,
                         "-WritersStopped"],
                        cwd=root, capture_output=True, text=True, check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    message = "Recovery digest mismatch" if corrupt_digest else "Pinned recovery script hash mismatch"
                    self.assertIn(message, result.stderr)
                    self.assertNotIn("untrusted helper executed", result.stderr)
                    self.assertNotIn("unsupported_os_not_executed", result.stderr)


class DirectBoundaries(unittest.TestCase):
    def test_prepare_passes_running_script_directory_to_imported_source_guard(self):
        self.assertEqual(ENTRY.read_text().count(
            "Assert-DirectSource $Source $SourceCommit $PSScriptRoot"
        ), 2)

    def test_direct_install_no_force_no_recursive_deletion_or_binary_promotion(self):
        text = ENTRY.read_text()
        self.assertIn("@('install','--locked','uv')", text)
        for forbidden in ("--force", "Remove-Item", "Copy-Tree", "Set-Acl", "Start-Sleep"):
            self.assertNotIn(forbidden, text)
        self.assertIn("MISE_ENABLE_TOOLS='uv'", text)
        self.assertIn("$psi.Environment.Clear()", text)
        self.assertIn("MISE_PLUGINS_DIR=", text)
        self.assertIn("MISE_SYSTEM_CONFIG_FILE=", text)

    def test_snapshot_hash_and_saved_scripts_checked_before_loading_helpers(self):
        text = ENTRY.read_text()
        self.assertLess(text.index("Recovery digest mismatch"), text.index(". (Join-Path"))
        self.assertLess(text.index("Pinned recovery script hash mismatch"), text.index(". (Join-Path"))
        self.assertIn("inventoryCommit=$inventoryReport.sourceCommit", text)
        self.assertNotIn("$SourceCommit -ne $inventoryReport.sourceCommit", text)


if __name__ == "__main__":
    unittest.main()
