"""Test the bounded inheritance policy, without Windows APIs or installation."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from test_windows_uv_metadata import TREE


ROOT = Path(__file__).resolve().parent.parent
DIRECTORY = ROOT / "tests/manual/windows-uv"
PWSH = os.environ.get("PWSH") or shutil.which("pwsh")
PRIVATE = (
    "O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
    "(A;OICI;FA;;;S-1-5-21-201-202-203-204)"
)
LIVE = PRIVATE + (
    "(A;OICI;0x1301bf;;;S-1-15-2-101)"
    "(A;OICI;0x1301bf;;;S-1-15-2-102)"
    "(A;OICI;0x1201bf;;;S-1-5-21-101-102-103-104)"
)
HARNESS = r"""
$ErrorActionPreference='Stop'
. (Join-Path $env:TEST_ENTRY 'uv-state.ps1')
$inputData=$env:TEST_DATA | ConvertFrom-Json -AsHashtable
try {
    if ($inputData.mode -eq 'inherit') {
        $result=Get-InheritedSddl $inputData.parent $inputData.creator $inputData.kind
    } else {
        $before=Get-Json $inputData
        $result=Get-CopyRequirements $inputData.tree @{sddl=$inputData.parent} $inputData.baseline -Publication:$inputData.publication
        Assert-Equal (Get-Json $inputData) $before 'Policy mutated sealed input'
    }
    ConvertTo-Json -InputObject $result -Depth 50 -Compress
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""
COPY_HARNESS = r"""
$ErrorActionPreference='Stop'
. (Join-Path $env:TEST_ENTRY 'uv-state.ps1')
$data=$env:TEST_DATA | ConvertFrom-Json -AsHashtable
$script:created=@{}; $script:events=@(); $script:sourceReads=0
$script:sourceTree=$data.tree
function Assert-Path {}
function Test-Path([string]$LiteralPath) { $script:created.ContainsKey($LiteralPath) }
function Read-Parent([string]$Path) {
    if ($script:created.ContainsKey($Path)) {
        $node=Get-Json $script:created[$Path] | ConvertFrom-Json -AsHashtable
        $null=$node.Remove('created'); $null=$node.Remove('written')
        return $node
    }
    return @{sddl=$data.parent;identity='parent'}
}
function Read-Tree([string]$Path) {
    if ($Path -eq '/source') {
        $script:sourceReads++
        $copy=Get-Json $script:sourceTree | ConvertFrom-Json -AsHashtable
        if ($data.fault -eq 'source' -and $script:sourceReads -gt 1) { $copy.nodes[0].identity='replaced' }
        return $copy
    }
    $nodes=@($script:created.Keys | Sort-Object | ForEach-Object {
        Get-Json $script:created[$_] | ConvertFrom-Json -AsHashtable
    })
    if ($data.fault -eq 'destination') { $nodes[0].sddl+='(A;ID;FA;;;WD)' }
    return @{kind='directory';nodes=$nodes}
}
function New-ExclusiveDirectory([string]$Path) {
    $script:events+="create:$Path"
    $sddl=Get-InheritedSddl (Read-Parent (Split-Path $Path)).sddl 'O:SYG:SYD:' 'directory'
    $script:created[$Path]=@{sddl=$sddl;identity="copy:$Path";kind='directory'}
}
function Set-Node([string]$Path,$Node,[switch]$KeepDacl) {
    $script:events+="set:$Path/private=$KeepDacl"
    foreach ($key in $Node.Keys) {
        if ($key -eq 'identity' -or ($KeepDacl -and $key -eq 'sddl')) { continue }
        $script:created[$Path][$key]=$Node[$key]
    }
}
try {
    $publication=if ($data.publication) {
        Get-CopyRequirements $script:sourceTree @{sddl=$data.parent} $script:sourceTree -Publication
    } else { $null }
    Copy-Tree '/source' '/destination' $script:sourceTree $publication
    @{events=$script:events;sourceReads=$script:sourceReads;tree=(Read-Tree '/destination')} |
        ConvertTo-Json -Depth 50 -Compress
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""


@unittest.skipUnless(PWSH, "pwsh is required")
class WindowsUvAclTests(unittest.TestCase):
    def invoke(self, data):
        return subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", HARNESS],
            cwd=ROOT, env=os.environ | {
                "TEST_ENTRY": str(DIRECTORY), "TEST_DATA": json.dumps(data),
            }, capture_output=True, text=True, check=False,
        )

    def inherit(self, parent, kind="file", creator="O:SYG:BAD:"):
        return self.invoke(dict(mode="inherit", parent=parent, creator=creator, kind=kind))

    def policy(self, tree, parent=PRIVATE, baseline=None, publication=False):
        result = self.invoke(dict(
            mode="requirements", tree=tree, parent=parent,
            baseline=tree if baseline is None else baseline, publication=publication,
        ))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_private_copy_uses_private_parent_not_source_inherited_aces(self):
        source = deepcopy(TREE)
        source["nodes"][0]["sddl"] = LIVE.replace("D:P", "D:AI").replace("OICI", "ID")
        copied = self.policy(source)
        self.assertEqual(
            copied["nodes"][0]["sddl"],
            PRIVATE.replace("D:P", "D:AI").replace("OICI", "ID"),
        )
        self.assertNotIn("identity", copied["nodes"][0])
        for field in ("hash", "attributes", "created", "written", "sacl"):
            self.assertEqual(copied["nodes"][0][field], source["nodes"][0][field])
        # Publication reuses all six original ACEs, not the three private ACEs.
        desired = self.policy(copied, LIVE, source, publication=True)
        self.assertEqual(desired["nodes"][0]["sddl"], source["nodes"][0]["sddl"])

    def test_existing_explicit_and_protected_acl_is_preserved_for_publication(self):
        original = deepcopy(TREE)
        original["nodes"][0]["sddl"] = "O:BAG:SYD:P(D;;FW;;;WD)(A;;FA;;;SY)"
        private = self.policy(original)
        self.assertTrue(private["nodes"][0]["sddl"].startswith("O:BAG:SYD:AI"))
        published = self.policy(private, LIVE, original, publication=True)
        self.assertEqual(published["nodes"][0]["sddl"], original["nodes"][0]["sddl"])

    def test_new_descendants_use_selected_publication_parent_recursively(self):
        original = deepcopy(TREE)
        original["kind"] = "directory"
        original["nodes"][0].update(
            kind="directory", hash=None, attributes=16, sddl=LIVE,
        )
        blob = self.policy(original)
        blob["nodes"].extend([
            blob["nodes"][0] | {"relative": "new"},
            TREE["nodes"][0] | {"relative": r"new\uv.exe"},
        ])
        desired = self.policy(blob, LIVE, original, publication=True)
        self.assertEqual(desired["nodes"][0]["sddl"], LIVE)
        self.assertIn("(A;OICIID;0x1301bf;;;S-1-15-2-101)", desired["nodes"][1]["sddl"])
        self.assertIn("(A;ID;0x1201bf;;;S-1-5-21-101-102-103-104)", desired["nodes"][2]["sddl"])
        self.assertFalse(any("identity" in n for n in desired["nodes"]))
        # Deleted parents are not consulted for a new subtree.
        replaced = self.policy(blob, PRIVATE, TREE, publication=True)
        self.assertNotIn("S-1-15", replaced["nodes"][2]["sddl"])

    def test_new_root_uses_live_acl_but_sealed_creator_owner_and_group(self):
        blob = deepcopy(TREE)
        blob["nodes"][0]["sddl"] = "O:BAG:SYD:AI(A;ID;FA;;;SY)"
        absent = {"kind": "absent", "nodes": []}
        desired = self.policy(blob, LIVE, absent, publication=True)
        self.assertTrue(desired["nodes"][0]["sddl"].startswith("O:BAG:SYD:AI"))
        self.assertIn("S-1-15-2-101", desired["nodes"][0]["sddl"])
        self.assertEqual(self.policy(absent, LIVE, TREE, True), absent)

    def test_inheritance_flags_are_applied_not_discarded(self):
        base = "O:SYG:SYD:P(A;OICI;FA;;;SY)"
        for flags, file_flags, directory_flags in (
            ("OI", "ID", "OIIOID"), ("CI", None, "CIID"),
            ("OICI", "ID", "OICIID"), ("OICINP", "ID", "ID"),
            ("CINP", None, "ID"), ("OINP", "ID", None),
            ("OICIIO", "ID", "OICIID"), ("OICIIOID", "ID", "OICIID"),
            ("", None, None), ("IO", None, None),
        ):
            for kind, expected in (("file", file_flags), ("directory", directory_flags)):
                with self.subTest(flags=flags, kind=kind):
                    result = self.inherit(base + f"(D;{flags};FW;;;WD)", kind)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    value = json.loads(result.stdout)
                    if expected is None:
                        self.assertNotIn(";;;WD", value)
                    else:
                        self.assertTrue(value.endswith(f"(D;{expected};FW;;;WD)"))

    def test_parent_order_deny_rights_and_creator_identity_remain_significant(self):
        parent = "O:SYG:SYD:P(D;OICI;FW;;;WD)(A;OICI;FR;;;SY)"
        result = self.inherit(parent, creator="O:BAG:SYD:")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout), "O:BAG:SYD:AI(D;ID;FW;;;WD)(A;ID;FR;;;SY)",
        )

    def test_unsupported_parent_acl_fails_closed_without_values(self):
        for dacl in (
            "", "NO_ACCESS_CONTROL", "(A;;FA;;;SY)",
            "(XA;OICI;FR;;;WD;condition)", "(OA;OICI;FR;guid;;WD)",
            "(A;OICI;GA;;;SY)", "(A;OICI;0x80000000;;;SY)",
            "(A;OICI;FA;;;CO)", "(A;OICI;FA;;;S-1-3-1)",
            "(A;OICISA;FA;;;SY)", "(A;OICI;FA;;;SY)garbage",
        ):
            with self.subTest(dacl=dacl):
                result = self.inherit("O:SYG:SYD:" + dacl)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn("O:SY", result.stderr)
                self.assertNotIn("S-1-3-1", result.stderr)

    def test_private_new_nodes_cannot_adopt_installer_supplied_acl_or_owner(self):
        tree = deepcopy(TREE)
        tree["nodes"][0]["sddl"] = "O:BAG:BAD:P(A;;FA;;;WD)"
        expected = self.policy(tree, baseline={"kind": "absent", "nodes": []})
        self.assertEqual(
            expected["nodes"][0]["sddl"], PRIVATE.replace("D:P", "D:AI").replace("OICI", "ID"),
        )

    def test_snapshot_plan_and_copy_contracts_are_wired_separately(self):
        entry = (DIRECTORY / "windows-uv.ps1").read_text(encoding="utf-8")
        helper = (DIRECTORY / "uv-state.ps1").read_text(encoding="utf-8")
        self.assertIn("schema=3", entry)
        self.assertIn("$state.schema -ne 3", entry)
        self.assertIn("$plan.schema -notin @(3,4)", entry)
        self.assertIn("schema=4; snapshotDigest=$SnapshotDigest", entry)
        self.assertIn("$entry.observation", entry)
        self.assertIn("$state.entries[$i].work 'Prepared private work changed'", entry)
        self.assertIn("Copy-Tree $Blob $stage $entry.blobState $Desired", entry)
        self.assertIn("(Read-Tree $entry.blob) $entry.blobState", entry)
        self.assertIn("Assert-Equal $entry.after $requirements", entry)
        self.assertIn("Assert-Equal (Read-Parent $path)", entry)
        self.assertNotIn("$node.sddl = $old[0].sddl", entry)
        copy = helper.split("function Copy-Tree", 1)[1].split("function Move-Tree", 1)[0]
        self.assertIn("-KeepDacl:($null -eq $Publication)", copy)
        self.assertIn("Assert-Observed (Read-Tree $Destination) $desired", copy)
        self.assertIn("Assert-Equal (Read-Tree $Source) $Expected", copy)
        move = helper.split("function Move-Tree", 1)[1].split("function Invoke-Captured", 1)[0]
        self.assertNotIn("Set-Node", move)
        self.assertNotIn("Set-Acl", move)
        self.assertNotIn("Assert-Observed", move)

    def test_real_copy_driver_orders_parent_acl_and_preserves_strict_source_checks(self):
        source = deepcopy(TREE)
        source["kind"] = "directory"
        source["nodes"][0].update(
            kind="directory", attributes=16, hash=None,
            sddl=LIVE.replace("D:P", "D:AI").replace("OICI", "OICIID"),
        )
        source["nodes"].append(source["nodes"][0] | {"relative": "child", "identity": "child-id"})
        for publication in (False, True):
            for fault in ("", "source", "destination"):
                with self.subTest(publication=publication, fault=fault):
                    result = subprocess.run(
                        [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", COPY_HARNESS],
                        cwd=ROOT, env=os.environ | {
                            "TEST_ENTRY": str(DIRECTORY),
                            "TEST_DATA": json.dumps(dict(
                                tree=source, parent=LIVE if publication else PRIVATE,
                                publication=publication, fault=fault,
                            )),
                        }, capture_output=True, text=True, check=False,
                    )
                    if fault:
                        self.assertEqual(result.returncode, 1)
                        self.assertIn(
                            "Source changed during copy" if fault == "source"
                            else "Copy does not meet destination ACL/metadata requirements",
                            result.stderr,
                        )
                        continue
                    self.assertEqual(result.returncode, 0, result.stderr)
                    output = json.loads(result.stdout)
                    self.assertEqual(output["sourceReads"], 2)
                    events = output["events"]
                    private = "False" if publication else "True"
                    self.assertLess(
                        events.index(f"set:/destination/private={private}"),
                        events.index("create:/destination/child"),
                    )
                    if not publication:
                        self.assertTrue(all("private=True" in e for e in events if e.startswith("set:")))


if __name__ == "__main__":
    unittest.main()
