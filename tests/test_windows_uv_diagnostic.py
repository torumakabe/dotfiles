"""Bounded diagnostic state transitions; no Windows filesystem APIs are executed."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests/manual/windows-uv"
PWSH = os.environ.get("PWSH") or shutil.which("pwsh")
HARNESS = r"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $env:TEST_ENTRY 'uv-state.ps1')
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $env:TEST_ENTRY 'diagnose-windows-uv.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($node in $ast.FindAll({param($n)
    $n -is [Management.Automation.Language.FunctionDefinitionAst]
},$true)) { . ([scriptblock]::Create($node.Extent.Text)) }
if ($env:TEST_MODE -eq 'native-capture') {
    $helper=Get-Content (Join-Path $env:TEST_ENTRY 'uv-state.ps1') -Raw
    $csharp=[regex]::Match($helper,"(?s)using System;.*?(?=\r?\n'@)").Value
    $declaration='[DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)]' +
        "`n  public static extern bool MoveFileExW(string source, string destination, uint flags);"
    $stub=@'
public static int Calls=0, Code=0; public static uint Flags=99;
  public static bool MoveFileExW(string source, string destination, uint flags) {
   Calls++; Flags=flags;
   Marshal.SetLastPInvokeError(Code);
   return Code == 0;
  }
'@
    if (-not $csharp.Contains($declaration)) { throw 'Native declaration not found' }
    Add-Type -TypeDefinition $csharp.Replace($declaration,$stub)
    [N4Uv.FileInfo]::Code=[int]$env:TEST_CODE
    $failure=$null
    try { Invoke-TreeRename 'fake-stage' 'fake-live' }
    catch { $failure=Get-DiagnosticError $_.Exception }
    @{calls=[N4Uv.FileInfo]::Calls; flags=[N4Uv.FileInfo]::Flags; error=$failure} |
        ConvertTo-Json -Depth 10 -Compress
    exit
}
# File and path stubs are confined to this process; writes are recorded in memory.
$FixtureRoot='/fixture'
$script:diagnosticRoots=@('/fixture','/uv/.n4-live','/uv/.n4-stage')
$script:transactionPaths=@('/uv/.n4-live','/fixture/retained-original','/uv/.n4-stage','/fixture/candidate')
$script:diagnosticEvents=[Collections.Generic.List[object]]::new()
$script:writes=[Collections.Generic.List[string]]::new()
$script:moves=[Collections.Generic.List[object]]::new()
$script:publicationCopies=[Collections.Generic.List[object]]::new()
$old=@{kind='directory'; nodes=@(@{identity='old';relative='';sddl='O:SYG:SYD:'})}
$new=@{kind='directory'; nodes=@(@{identity='new';relative='';sddl='O:SYG:SYD:'})}
$script:files=@{
    '/uv/.n4-live'=$old; '/uv/.n4-stage'=$new
    '/uv/0.12.10'=@{kind='protected-live'}
    '/backup'=@{kind='protected-backup'}
}
function Assert-Path {}
# Host separators differ; keep the exact production ownership logic except its separator.
${function:Assert-DiagnosticPath}=[scriptblock]::Create(
    ${function:Assert-DiagnosticPath}.ToString().Replace("$"+"root+'\'","$"+"root+'/'"))
function Read-Tree($Path) {
    if ($script:files.ContainsKey($Path)) { return $script:files[$Path] }
    return @{kind='absent';nodes=@()}
}
function Write-NewJson($Path,$Value) {
    Assert-DiagnosticPath $Path
    if ($script:writes.Contains($Path)) { throw 'Evidence overwrite' }
    $script:writes.Add($Path)
}
function Copy-Tree($Source,$Destination,$Expected,$Desired) {
    $script:publicationCopies.Add(@{source=$Source;destination=$Destination;expected=$Expected;desired=$Desired})
    Assert-DiagnosticPath $Destination
    if ($script:files.ContainsKey($Destination)) { throw 'Destination exists' }
    Assert-Equal (Read-Tree $Source) $Expected 'Source differs'
    $script:files[$Destination]=Get-Json $Desired | ConvertFrom-Json -AsHashtable
    $script:writes.Add($Destination)
}
function Move-Tree($From,$To,$Expected) {
    $script:moves.Add(@($From,$To))
    if ($env:TEST_MODE -eq 'promotion-failure' -and $From -eq '/uv/.n4-stage') {
        $error=[ComponentModel.Win32Exception]::new(5,'injected')
        $error.Data['operation']='MoveFileExW: tree rename'
        $error.Data['source']=$From; $error.Data['destination']=$To
        throw $error
    }
    $script:files[$To]=$script:files[$From]; $script:files.Remove($From)
    if ($env:TEST_MODE -eq 'post-move-failure') { throw 'injected after native success' }
}
if ($env:TEST_MODE -like 'finally-*') {
    $Backup='/backup'; $ApprovedUvParent='/uv'; $source='/source'; $SourceCommit='pinned'; $commit='pinned'
    function Read-DiagnosticInputs { Read-Tree $Backup }
    $backupBefore=Read-DiagnosticInputs
    $parentBefore=@{identity='parent'}; $siblingsBefore=@{identity='siblings'}
    $state=@{entries=@(@{target='/uv/0.12.10';original=(Read-Tree '/uv/0.12.10')})}
    $script:checked=[Collections.Generic.List[string]]::new()
    function Read-Parent { $script:checked.Add('parent'); return $parentBefore }
    function Read-DiagnosticSiblings { $script:checked.Add('siblings'); return $siblingsBefore }
    function Get-SourceCommit { $script:checked.Add('source'); return $commit }
    if ($env:TEST_MODE -like '*damaged') {
        $script:files['/backup']=@{kind='changed'}
        $script:files['/uv/0.12.10']=@{kind='changed'}
    }
    $result=@{status='failed';error=@{code=5;operation='MoveFileExW: tree rename'};invariantErrors=@()}
    if ($env:TEST_MODE -eq 'finally-success-damaged') { $result.status='synthetic_restored' }
    $finally=@($ast.EndBlock.Statements | Where-Object {
        $_ -is [Management.Automation.Language.TryStatementAst]
    })[-1].Finally.Extent.Text
    $null=. ([scriptblock]::Create($finally.Substring(1,$finally.Length-2)))
    @{result=$result; checked=$script:checked; moves=$script:moves; writes=$script:writes} |
        ConvertTo-Json -Depth 20 -Compress
    exit
}
$failure=$null
try {
    switch ($env:TEST_MODE) {
        'guard' { Assert-DiagnosticPath $env:TEST_PATH }
        'occupied' { $script:files['/fixture/retained-original']=$new; Invoke-DiagnosticTransaction $old $new }
        'changed-source' { Invoke-DiagnosticTransaction $new $new }
        'direct-input' {
            Invoke-DiagnosticMove 'forbidden' '/backup' '/uv/0.12.10' @() @()
        }
        'nested-move' {
            Invoke-DiagnosticMove 'forbidden' '/uv/.n4-live/child' '/fixture/child' @() @()
        }
        'copy-input' { Copy-DiagnosticTree '/uv/.n4-live' '/backup' $old $old }
        'copy-metadata-mismatch' {
            $desired=Get-Json $old | ConvertFrom-Json -AsHashtable
            $desired.kind='file'
            Copy-DiagnosticTree '/uv/.n4-live' '/uv/.n4-stage' $old $desired
        }
        'publication-copy' {
            $script:files.Remove('/uv/.n4-stage')
            $desired=Get-Json $old | ConvertFrom-Json -AsHashtable
            $desired.nodes[0].sddl='O:SYG:BAD:AI(A;OICI;FA;;;SY)'
            Copy-DiagnosticTree '/uv/.n4-live' '/uv/.n4-stage' $old $desired -PublicationCopy
        }
        'publication-input' {
            Copy-DiagnosticTree '/uv/.n4-live' '/backup' $old $old -PublicationCopy
        }
        'publication-metadata-mismatch' {
            $desired=Get-Json $old | ConvertFrom-Json -AsHashtable
            $desired.kind='file'
            Copy-DiagnosticTree '/uv/.n4-live' '/uv/.n4-stage' $old $desired -PublicationCopy
        }
        default { Invoke-DiagnosticTransaction $old $new }
    }
} catch { $failure=Get-DiagnosticError $_.Exception }
@{error=$failure; events=$script:diagnosticEvents; moves=$script:moves; writes=$script:writes
    files=$script:files; publicationCopies=$script:publicationCopies} | ConvertTo-Json -Depth 20 -Compress
"""


@unittest.skipUnless(PWSH, "pwsh is required")
class WindowsUvDiagnosticTests(unittest.TestCase):
    def run_case(self, mode, **extra):
        result = subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", HARNESS],
            cwd=ROOT, env=os.environ | {"TEST_ENTRY": str(FIXTURES), "TEST_MODE": mode} | extra,
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_protected(self, result, *, copy_writes=()):
        self.assertEqual(result["files"]["/backup"], {"kind": "protected-backup"})
        self.assertEqual(result["files"]["/uv/0.12.10"], {"kind": "protected-live"})
        for source, dest in result["moves"]:
            self.assertIn(source, (
                "/uv/.n4-live", "/uv/.n4-stage", "/fixture/retained-original",
            ))
            self.assertIn(dest, (
                "/uv/.n4-live", "/fixture/retained-original", "/fixture/candidate",
            ))
        self.assertEqual(result["writes"], list(copy_writes) + [
            f"/fixture/phase-{i + 1}.json" for i in range(len(result["events"]))
        ])

    def test_atomic_native_capture_success_and_errors(self):
        for code in (0, 5, 32):
            with self.subTest(code=code):
                result = self.run_case("native-capture", TEST_CODE=str(code))
                self.assertEqual((result["calls"], result["flags"]), (1, 0))
                if not code:
                    self.assertIsNone(result["error"])
                else:
                    self.assertEqual(result["error"]["type"], "System.ComponentModel.Win32Exception")
                    self.assertEqual(result["error"]["code"], code)
                    self.assertEqual(result["error"]["operation"], "MoveFileExW: tree rename")
                    self.assertEqual(result["error"]["source"], "fake-stage")
                    self.assertEqual(result["error"]["destination"], "fake-live")

    def test_complete_transaction_reuses_vacated_name_then_restores_identity(self):
        result = self.run_case("success")
        self.assertIsNone(result["error"])
        self.assertEqual([event["phase"] for event in result["events"]], [
            "evacuate", "promote-same-name", "unpublish", "restore-fake-original",
        ])
        self.assertEqual(result["moves"][0][0], result["moves"][1][1])
        self.assertEqual(result["files"]["/uv/.n4-live"]["nodes"][0]["identity"], "old")
        self.assertEqual(result["files"]["/fixture/candidate"]["nodes"][0]["identity"], "new")
        self.assertNotIn("/uv/.n4-stage", result["files"])
        for event in result["events"]:
            self.assertGreaterEqual(event["elapsedMilliseconds"], 0)
        self.assert_protected(result)

    def test_promotion_failure_retains_evacuated_original_and_stage_without_retry(self):
        result = self.run_case("promotion-failure")
        self.assertEqual(len(result["moves"]), 2)
        self.assertEqual(result["error"]["code"], 5)
        self.assertEqual(result["events"][-1]["error"], result["error"])
        self.assertNotIn("/uv/.n4-live", result["files"])
        self.assertEqual(result["files"]["/fixture/retained-original"]["nodes"][0]["identity"], "old")
        self.assertEqual(result["files"]["/uv/.n4-stage"]["nodes"][0]["identity"], "new")
        self.assert_protected(result)

    def test_post_move_check_failure_does_not_attempt_promotion_or_recovery(self):
        result = self.run_case("post-move-failure")
        self.assertEqual(len(result["moves"]), 1)
        self.assertNotIn("/uv/.n4-live", result["files"])
        self.assertIsNone(result["error"]["code"])
        self.assert_protected(result)

    def test_changed_or_occupied_state_and_direct_inputs_prevent_every_move(self):
        for mode in ("occupied", "changed-source", "direct-input", "nested-move",
                     "copy-input", "copy-metadata-mismatch"):
            with self.subTest(mode=mode):
                result = self.run_case(mode)
                self.assertIsNotNone(result["error"])
                self.assertEqual(result["moves"], [])
                self.assert_protected(result)

    def test_write_guard_rejects_inputs_real_live_and_prefix_collisions(self):
        for path in ("/backup", "/backup/input", "/uv/0.12.10", "/fixture-other/a", "/uv/.n4-live-other"):
            with self.subTest(path=path):
                result = self.run_case("guard", TEST_PATH=path)
                self.assertIn("Outside freshly owned", result["error"]["message"])
                self.assertEqual(result["moves"], [])
                self.assertEqual(result["writes"], [])

    def test_publication_mode_reuses_production_copy_with_publication_requirements(self):
        result = self.run_case("publication-copy")
        self.assertIsNone(result["error"])
        self.assertEqual(len(result["publicationCopies"]), 1)
        copy = result["publicationCopies"][0]
        self.assertEqual((copy["source"], copy["destination"]), ("/uv/.n4-live", "/uv/.n4-stage"))
        self.assertNotEqual(copy["expected"]["nodes"][0]["sddl"], copy["desired"]["nodes"][0]["sddl"])
        self.assertEqual(result["files"]["/uv/.n4-stage"], copy["desired"])
        self.assertEqual(result["moves"], [])
        self.assert_protected(result, copy_writes=("/uv/.n4-stage",))

    def test_publication_mode_cannot_bypass_input_and_metadata_guards(self):
        for mode in ("publication-input", "publication-metadata-mismatch"):
            with self.subTest(mode=mode):
                result = self.run_case(mode)
                self.assertIsNotNone(result["error"])
                self.assertEqual(result["publicationCopies"], [])
                self.assertEqual(result["writes"], [])
                self.assert_protected(result)

    def test_finally_checks_all_invariants_after_failure_without_losing_native_error(self):
        for mode, failures in (("finally-clean", 0), ("finally-damaged", 2),
                               ("finally-success-damaged", 2)):
            with self.subTest(mode=mode):
                result = self.run_case(mode)
                self.assertEqual(result["result"]["status"], "failed")
                self.assertEqual(result["result"]["error"]["code"], 5)
                self.assertEqual(len(result["result"]["invariantErrors"]), failures)
                self.assertEqual(result["checked"], ["parent", "siblings", "source"])
                self.assertEqual(result["moves"], [])
                self.assertEqual(result["writes"], ["/fixture/result.json"])

    def test_entry_requires_writers_gate_before_os_checks_or_writes(self):
        result = subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
             str(FIXTURES / "diagnose-windows-uv.ps1"),
             "-Backup", "unused", "-SnapshotDigest", "unused", "-PlanDigest", "unused",
             "-ApprovedUvParent", "unused", "-FixtureRoot", "unused", "-SourceCommit", "unused"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Explicit -WritersStopped", result.stderr)

    def test_entry_preserves_preconditions_and_read_only_inputs(self):
        source = (FIXTURES / "diagnose-windows-uv.ps1").read_text()
        helper = (FIXTURES / "uv-state.ps1").read_text()
        self.assertNotIn("Set-Acl", source)
        self.assertNotIn("Set-Node", source)
        self.assertEqual(source.count("Copy-Tree $Source $Destination $Expected $Desired"), 1)
        self.assertIn("if ($PublicationCopy)", source)
        self.assertIn("$publicationCopy=$UsePublicationCopy -and $copy.phase -eq 'copy-candidate'", source)
        self.assertIn("-PublicationCopy:$publicationCopy", source)
        self.assertLess(source.index("Assert-DiagnosticPath $Destination"), source.index("if ($PublicationCopy)"))
        self.assertNotIn("Remove-Item", source)
        self.assertNotIn("Save-Journal", source)
        self.assertNotIn("Start-Sleep", source)
        for check in (
            "FixtureRoot exists; never reuse evidence.",
            "FixtureRoot must be independent",
            "FixtureRoot must not overlap any real target, including absent targets",
            "Generated diagnostic name already exists",
            "$journal.phase -ne 'restored'",
            "Assert-Beneath $path $Backup",
            "Get-SourceCommit $source $SourceCommit",
            "Read-DiagnosticInputs) $backupBefore",
            "Read-DiagnosticSiblings) $siblingsBefore",
            "Read-Tree $entry.target) $entry.original",
            "simulated_only=$true; sandboxSuccess=$false",
        ):
            self.assertIn(check, source)
        move = helper.split("function Move-Tree(")[1].split("function Invoke-Captured(")[0]
        self.assertNotIn("GetLastWin32Error", move)
        self.assertEqual(move.count("Invoke-TreeRename $Source $Destination"), 1)
        self.assertIn("Move destination exists", move)
        self.assertIn("Local fixed NTFS required", move)
        self.assertIn("Renamed object changed", move)
        self.assertLess(
            source.index("if (-not $WritersStopped)"),
            source.index("New-ExclusiveDirectory $FixtureRoot"),
        )


if __name__ == "__main__":
    unittest.main()
