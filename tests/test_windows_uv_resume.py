"""Verification-only resume contracts, without Windows or a real installer."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "tests/manual/windows-uv"
PWSH = os.environ.get("PWSH") or shutil.which("pwsh")
HARNESS = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $env:TEST_ENTRY 'uv-state.ps1')
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $env:TEST_ENTRY 'windows-uv.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($node in $ast.EndBlock.Statements | Where-Object {
    $_ -is [Management.Automation.Language.FunctionDefinitionAst]
}) { . ([scriptblock]::Create($node.Extent.Text)) }
$Backup=$env:TEST_ROOT
$path=Join-Path $Backup 'work\data\installs\uv'
$before=@{relative='';kind='directory';hash=$null;attributes=16;sacl='unobserved'
    sddl='O:SYG:SYD:AI(A;OICI;FA;;;SY)';identity='12345678:0000000000000001'}
$after=Get-Json $before | ConvertFrom-Json -AsHashtable
$after.identity='12345678:0000000000000002'
$state=@{parents=@{};entries=@()}
$state.parents[$path]=$before
$other=Join-Path $Backup 'observations'
$state.parents[$other]=$before
$actual=@{}; $actual[$path]=$after; $actual[$other]=$before
$execution=@{sourceCommit=('a'*40);scripts=@{'windows-uv.ps1'='A';'uv-state.ps1'='B'}}
$journal=@{phase='install-started';records=@{}}
$status=@{exitCode=0;isolated=$true;output='withheld_to_avoid_secrets';sandboxSuccess=$false}
$script:saves=0
function Save-Journal($Journal) {
    $script:saves++
    $script:durable=Get-Json $Journal
}
function Read-Parent([string]$Path) {
    if ($env:TEST_CASE -eq 'unsafe-parent') { throw 'Unsupported reparse parent' }
    return $actual[$Path]
}
function Read-Tree([string]$Path) {
    if ($env:TEST_CASE -eq 'original-change') { return @{changed=$true} }
    return @{kind='absent';nodes=@()}
}
$errorMessage=''
try {
    switch ($env:TEST_CASE) {
        'unchanged' { $actual[$path]=$before }
        'volume' { $after.identity='87654321:0000000000000002' }
        'malformed-id' { $after.identity='invalid' }
        'kind' { $after.kind='file' }
        'sddl' { $after.sddl=$after.sddl.Replace('AI','') }
        'attributes' { $after.attributes=18 }
        'extra-field' { $after.extra='unexpected' }
        'missing-field' { $null=$after.Remove('hash') }
        'missing-parent' { $null=$state.parents.Remove($path) }
        'other-parent' { $actual[$other]=$after }
        'original-change' {
            $state.entries=@(@{target='live';saved='observation'
                original=@{kind='absent';nodes=@()};observation=@{kind='absent';nodes=@()}})
        }
        'exit-failed' { $status.exitCode=1 }
        'exit-string' { $status.exitCode='0' }
        'not-isolated' { $status.isolated=$false }
        'sandbox' { $status.sandboxSuccess=$true }
        'phase-prepared' { $journal.phase='prepared' }
        'phase-installed' { $journal.phase='installed' }
        'phase-applied' { $journal.phase='applied' }
        'phase-restored' { $journal.phase='restored' }
        'records' { $journal.records['0']=@{} }
        'plan' { Write-NewJson (Join-Path $Backup 'plan.json') @{} }
    }
    if ($env:TEST_CASE -ne 'missing-status') {
        Write-NewJson (Join-Path $Backup 'install-status.json') $status
    }
    $snapshotBefore=Get-Json $state
    $seal=Start-InstallValidation $state $journal $execution
    Assert-Equal (Get-Json $state) $snapshotBefore 'Snapshot mutated'
    Assert-Parents $state $seal.parents
    $journal=$script:durable | ConvertFrom-Json -AsHashtable
    if ($env:TEST_CASE -eq 'later-id') {
        $actual[$path]=Get-Json $after | ConvertFrom-Json -AsHashtable
        $actual[$path].identity='12345678:0000000000000003'
    }
    if ($env:TEST_CASE -eq 'later-code') { $execution.scripts['windows-uv.ps1']='C' }
    if ($env:TEST_CASE -eq 'seal-scope') { $journal.validation.parents[$other]=$before }
    $null=Start-InstallValidation $state $journal $execution
    Assert-Equal (Get-Json $state) $snapshotBefore 'Snapshot mutated on retry'
} catch { $errorMessage=$_.Exception.Message }
@{error=$errorMessage;saves=$script:saves} | ConvertTo-Json -Compress
"""

PIPELINE = r"""
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $env:TEST_ENTRY 'uv-state.ps1')
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $env:TEST_ENTRY 'windows-uv.ps1'),[ref]$tokens,[ref]$errors)
foreach ($node in $ast.EndBlock.Statements | Where-Object {
    $_ -is [Management.Automation.Language.FunctionDefinitionAst]
}) { . ([scriptblock]::Create($node.Extent.Text)) }
$Backup=$env:TEST_ROOT
$homeRoot='fixture-home'
$Command='VerifyInstall'
$VerificationOnlySource=$true
$UseExistingGitHubAuth=$false
$script:installerCalls=0
$work=Join-Path $Backup 'work'
$targets=@(Get-Targets (Join-Path $work 'config/config.toml') (Join-Path $work 'data') (Join-Path $work 'cache'))
$node=@{relative='';kind='directory';hash=$null;attributes=16;sacl='unobserved'
    sddl='O:SYG:SYD:AI(A;OICI;FA;;;SY)';identity='12345678:0000000000000001'}
$script:actual=@{}
$state=@{schema=3;home=$homeRoot;parents=@{};entries=@();mise='fixture-mise';miseHash='M'
    chezmoi='fixture-chezmoi';candidateHashes=@('C','L');otherMetadata=@{}
    data=(Join-Path $Backup 'live/data')}
foreach ($target in $targets) {
    $parent=Split-Path $target
    $state.parents[$parent]=$node
    $script:actual[$parent]=$node
    $state.entries+=@{target=$target.Replace('work','live');saved='observations/0'
        original=@{kind='absent';nodes=@()};observation=@{kind='absent';nodes=@()}
        work=@{kind='absent';nodes=@()}}
    $state.parents[(Split-Path $state.entries[-1].target)]=$node
    $script:actual[(Split-Path $state.entries[-1].target)]=$node
}
$replaced=Join-Path $Backup 'work/data/installs/uv'
$script:actual[$replaced]=Get-Json $node | ConvertFrom-Json -AsHashtable
$script:actual[$replaced].identity='12345678:0000000000000002'
$execution=@{sourceCommit=('a'*40);scripts=@{'windows-uv.ps1'='A';'uv-state.ps1'='B'}}
$journal=@{phase='install-started';records=@{}}
if ($env:TEST_CASE -in @('repeat-installer','normal-install')) {
    $Command='Install'
    $journal.phase='prepared'
}
if ($env:TEST_CASE -eq 'normal-install') {
    $VerificationOnlySource=$false
    $script:actual[$replaced]=$node
}
Write-NewJson (Join-Path $Backup 'snapshot.json') $state
Write-NewJson (Join-Path $Backup 'journal.json') $journal
if ($env:TEST_CASE -ne 'normal-install') {
    Write-NewJson (Join-Path $Backup 'install-status.json') @{
        exitCode=0;isolated=$true;output='withheld_to_avoid_secrets';sandboxSuccess=$false}
}
foreach ($name in @('windows-uv.ps1','uv-state.ps1')) {
    [IO.File]::WriteAllText((Join-Path $Backup $name),'immutable old saved script')
}
$script:hashImplementation=${function:Get-Hash}
$SnapshotDigest=Get-Hash (Join-Path $Backup 'snapshot.json')
$protected=@{}
foreach ($name in @('snapshot.json','windows-uv.ps1','uv-state.ps1')) {
    $protected[$name]=Get-Hash (Join-Path $Backup $name)
}
[IO.Directory]::CreateDirectory((Split-Path $targets[0])) | Out-Null
[IO.Directory]::CreateDirectory((Split-Path $targets[3])) | Out-Null
[IO.File]::WriteAllText($targets[3],'fixture metadata')
$exeRoot=Join-Path $work 'data/installs/uv/0.12.10'
[IO.Directory]::CreateDirectory($exeRoot) | Out-Null
$pe=[byte[]]::new(128); $pe[60]=64; $pe[64]=80; $pe[65]=69; $pe[68]=100; $pe[69]=134
foreach ($name in @('uv','uvx')) { [IO.File]::WriteAllBytes((Join-Path $exeRoot "$name.exe"),$pe) }
function Get-Hash([string]$Path) {
    if ($Path -eq 'fixture-mise') { return 'M' }
    if ($Path -eq $targets[0]) { return 'C' }
    if ($Path -eq $targets[1]) { return 'L' }
    & $script:hashImplementation $Path
}
function Read-Parent([string]$Path) { $script:actual[$Path] }
function Read-Tree([string]$Path) {
    if ($Command -eq 'Restore' -and $Path.Contains('/work/')) { throw 'Restore must not read work' }
    if ($env:TEST_CASE -eq 'unsafe-output' -and $Path -eq $targets[2]) {
        throw 'Hardlink unsupported'
    }
    @{kind='absent';nodes=@()}
}
function Get-RecoveryExecution($State,$Plan) { $execution }
function Assert-MiseEnvironment {}
function Save-Journal($Journal) {
    if ($env:TEST_CASE -eq 'plan-before-journal' -and $Journal.phase -eq 'installed') {
        throw 'Injected interruption after plan creation'
    }
    [IO.File]::WriteAllText((Join-Path $Backup 'journal.json'),(Get-Json $Journal))
}
function ConvertTo-WindowsPath([string]$Path) { $Path }
function ConvertFrom-Toml { @{} }
function Get-WithoutUv { @{} }
function Set-CandidateMetadata {}
function Invoke-Captured($Exe,$Arguments,$Directory,$Environment) {
    if ('install' -in $Arguments) {
        if ($env:TEST_CASE -ne 'normal-install') { throw 'INSTALLER MUST NEVER RUN' }
        $script:installerCalls++
        $script:actual[$replaced]=Get-Json $node | ConvertFrom-Json -AsHashtable
        $script:actual[$replaced].identity='12345678:0000000000000002'
        return @{stdout='';exitCode=0}
    }
    $result=switch ($Arguments[0]) {
        'config' { Get-Json @(@{path=$targets[0]}) }
        'tool' {
            if ($env:TEST_CASE -eq 'bad-backend') { '{"backend":"aqua:astral-sh/uv"}' }
            else { '{"backend":"github:astral-sh/uv"}' }
        }
        'which' {
            $root=if ($Command -eq 'Apply') { $exeRoot.Replace('/work/','/live/') } else { $exeRoot }
            Join-Path $root ($Arguments[1]+'.exe')
        }
        '--version' { ([IO.Path]::GetFileNameWithoutExtension($Exe))+' 0.12.10' }
        default { throw 'Unexpected child invocation' }
    }
    @{stdout=$result;exitCode=0}
}
$tail=$ast.Extent.Text.Substring($ast.Extent.Text.IndexOf('if (-not $SnapshotDigest'))
$errorMessage=''
try {
    # The production tail exits on success; run it in a child scope without terminating this harness.
    & ([scriptblock]::Create($tail.Replace('exit 0','return')))
} catch { $errorMessage=$_.Exception.Message }
if ($env:TEST_CASE -in @('apply','restore','later-apply-parent','plan-before-journal','repeat-verify')) {
    if ($env:TEST_CASE -eq 'plan-before-journal') {
        if ($errorMessage -cne 'Injected interruption after plan creation') { throw $errorMessage }
        $errorMessage=''
    } elseif ($errorMessage) { throw $errorMessage }
    $PlanDigest=Get-Hash (Join-Path $Backup 'plan.json')
    $Command=if ($env:TEST_CASE -eq 'repeat-verify') { 'VerifyInstall' } else { 'Apply' }
    if ($env:TEST_CASE -eq 'later-apply-parent') {
        $script:actual[$replaced].identity='12345678:0000000000000003'
    }
    try {
        & ([scriptblock]::Create($tail.Replace('exit 0','return')))
        if ($env:TEST_CASE -eq 'restore') {
            $Command='Restore'
            $script:actual=@{}
            & ([scriptblock]::Create($tail.Replace('exit 0','return')))
        }
    } catch { $errorMessage=$_.Exception.Message }
}
foreach ($name in $protected.Keys) {
    Assert-Equal (& $script:hashImplementation (Join-Path $Backup $name)) $protected[$name] 'Immutable input changed'
}
$plan=$null
if (Test-Path (Join-Path $Backup 'plan.json')) { $plan=Read-Json (Join-Path $Backup 'plan.json') }
$journal=Read-Json (Join-Path $Backup 'journal.json')
@{error=$errorMessage;plan=$plan;phase=$journal.phase;sealed=$journal.ContainsKey('validation')
    installerCalls=$script:installerCalls} |
    ConvertTo-Json -Compress -Depth 100
"""


@unittest.skipIf(sys.platform.startswith("linux"), "Windows resume tests do not run on Linux")
@unittest.skipUnless(PWSH, "pwsh is required")
class WindowsUvResumeTests(unittest.TestCase):
    def run_case(self, case: str, harness: str = HARNESS) -> dict:
        with tempfile.TemporaryDirectory(prefix=".windows-uv-resume-", dir=ROOT) as root:
            result = subprocess.run(
                [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", harness],
                cwd=ROOT, env=os.environ | {
                    "TEST_ENTRY": str(ENTRY), "TEST_ROOT": root, "TEST_CASE": case,
                }, text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout.splitlines()[-1])

    def test_only_isolated_parent_identity_can_change(self) -> None:
        for case in ("success", "unchanged"):
            with self.subTest(case=case):
                self.assertEqual(self.run_case(case), {"error": "", "saves": 1})

    def test_nonidentity_metadata_and_volume_remain_strict(self) -> None:
        for case in (
            "volume", "malformed-id", "kind", "sddl", "attributes",
            "extra-field", "missing-field", "missing-parent", "other-parent",
            "original-change", "unsafe-parent",
        ):
            with self.subTest(case=case):
                result = self.run_case(case)
                self.assertTrue(result["error"])
                self.assertEqual(result["saves"], 0)

    def test_requires_completed_isolated_installer_without_plan(self) -> None:
        for case in (
            "exit-failed", "exit-string", "not-isolated", "sandbox", "missing-status",
            "phase-prepared", "phase-installed", "phase-applied", "phase-restored",
            "records", "plan",
        ):
            with self.subTest(case=case):
                result = self.run_case(case)
                self.assertTrue(result["error"])
                self.assertEqual(result["saves"], 0)

    def test_durable_seal_rejects_subsequent_parent_or_code_changes(self) -> None:
        for case in ("later-id", "later-code", "seal-scope"):
            with self.subTest(case=case):
                result = self.run_case(case)
                self.assertTrue(result["error"])
                self.assertEqual(result["saves"], 1)

    def test_actual_resume_dispatch_preserves_immutable_inputs(self) -> None:
        result = self.run_case("success", PIPELINE)
        self.assertEqual(result["error"], "")
        self.assertEqual(result["phase"], "installed")
        self.assertTrue(result["sealed"])
        self.assertEqual(result["plan"]["schema"], 4)
        self.assertEqual(result["installerCalls"], 0)
        self.assertEqual(len(result["plan"]["entries"]), 14)
        self.assertEqual(len(result["plan"]["resolutions"]), 2)

    def test_failed_validation_keeps_seal_without_plan(self) -> None:
        for case in ("bad-backend", "unsafe-output"):
            with self.subTest(case=case):
                result = self.run_case(case, PIPELINE)
                self.assertTrue(result["error"])
                self.assertIsNone(result["plan"])
                self.assertTrue(result["sealed"])
                self.assertEqual(result["phase"], "install-started")

    def test_apply_and_offline_restore_consume_sealed_parent(self) -> None:
        for case, phase in (("apply", "applied"), ("restore", "restored"),
                            ("plan-before-journal", "applied")):
            with self.subTest(case=case):
                result = self.run_case(case, PIPELINE)
                self.assertEqual(result["error"], "")
                self.assertEqual(result["phase"], phase)

    def test_apply_rejects_later_parent_replacement(self) -> None:
        result = self.run_case("later-apply-parent", PIPELINE)
        self.assertIn("Parent identity/ACL/attributes changed", result["error"])
        self.assertEqual(result["phase"], "installed")

    def test_dispatch_cannot_repeat_installer_or_overwrite_plan(self) -> None:
        for case, message in (("repeat-installer", "Install is one-shot"),
                              ("repeat-verify", "plan already exists")):
            with self.subTest(case=case):
                result = self.run_case(case, PIPELINE)
                self.assertIn(message, result["error"])
                self.assertEqual(result["installerCalls"], 0)

    def test_normal_install_uses_same_validation_once(self) -> None:
        result = self.run_case("normal-install", PIPELINE)
        self.assertEqual(result["error"], "")
        self.assertEqual(result["phase"], "installed")
        self.assertEqual(result["plan"]["schema"], 4)
        self.assertEqual(result["installerCalls"], 1)


if __name__ == "__main__":
    unittest.main()
