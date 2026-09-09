"""Exercise copy comparisons without Windows filesystem operations."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parent.parent
PWSH = os.environ.get("PWSH") or shutil.which("pwsh")
SDDL = (
    "O:SYG:SYD:(A;ID;FA;;;SY)(A;ID;FA;;;BA)"
    "(A;ID;FA;;;S-1-12-1-1-2-3-4)"
)
TREE = {
    "kind": "file",
    "nodes": [{
        "relative": "", "kind": "file", "hash": "fixture-content",
        "attributes": 32, "created": 639088243998748307,
        "written": 639239883037101197, "sddl": SDDL,
        "sacl": "unobserved", "identity": "original-id",
    }],
}
HARNESS = r"""
$ErrorActionPreference = 'Stop'
. $env:TEST_HELPER
$left = $env:TEST_LEFT | ConvertFrom-Json -AsHashtable
$right = $env:TEST_RIGHT | ConvertFrom-Json -AsHashtable
$before = Get-Json @($left,$right)
try {
    if ($env:TEST_MODE -eq 'strict') { Assert-Equal $left $right 'strict mismatch' }
    else { Assert-Observed $left $right 'copy mismatch' }
    Assert-Equal (Get-Json @($left,$right)) $before 'Inputs were mutated'
    @{accepted=$true; observed=(Get-ObservedTree $left)} | ConvertTo-Json -Depth 10 -Compress
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""


@unittest.skipUnless(PWSH, "pwsh is required")
class WindowsUvMetadataTests(unittest.TestCase):
    def compare(self, left: dict, right: dict, mode: str = "copy"):
        return subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", HARNESS],
            cwd=ROOT, capture_output=True, text=True, check=False,
            env=os.environ | {
                "TEST_HELPER": str(ROOT / "tests/manual/windows-uv/uv-state.ps1"),
                "TEST_LEFT": json.dumps(left), "TEST_RIGHT": json.dumps(right),
                "TEST_MODE": mode,
            },
        )

    def copied(self) -> dict:
        copied = deepcopy(TREE)
        copied["nodes"][0]["identity"] = "copy-id"
        copied["nodes"][0]["sddl"] = SDDL.replace("D:", "D:AI")
        return copied

    def test_reported_auto_inherited_difference_is_copy_only(self) -> None:
        copied = self.copied()
        result = self.compare(copied, TREE)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)["observed"]["nodes"][0]
        self.assertEqual(observed["sddl"], SDDL)
        self.assertNotIn("identity", observed)
        copied["nodes"][0]["identity"] = TREE["nodes"][0]["identity"]
        strict = self.compare(copied, TREE, "strict")
        self.assertEqual(strict.returncode, 1)
        self.assertIn("strict mismatch", strict.stderr)

    def test_other_dacl_flags_remain_significant(self) -> None:
        for flags in ("P", "AR", "PAR"):
            with self.subTest(flags=flags):
                copied = self.copied()
                copied["nodes"][0]["sddl"] = SDDL.replace("D:", f"D:{flags}AI")
                rejected = self.compare(copied, TREE)
                self.assertEqual(rejected.returncode, 1)
                self.assertIn("nodes[0].sddl", rejected.stderr)
                expected = deepcopy(TREE)
                expected["nodes"][0]["sddl"] = SDDL.replace("D:", f"D:{flags}")
                self.assertEqual(self.compare(copied, expected).returncode, 0)

    def test_owner_group_aces_and_inheritance_are_not_ignored(self) -> None:
        for before, after in (
            ("O:SY", "O:BA"), ("G:SY", "G:BA"), ("FA", "FR"),
            ("A;ID", "D;ID"), ("A;ID", "A;"),
            (";;;BA", ";;;BU"),
            ("(A;ID;FA;;;SY)(A;ID;FA;;;BA)", "(A;ID;FA;;;BA)(A;ID;FA;;;SY)"),
        ):
            with self.subTest(change=(before, after)):
                copied = self.copied()
                copied["nodes"][0]["sddl"] = copied["nodes"][0]["sddl"].replace(before, after)
                result = self.compare(copied, TREE)
                self.assertEqual(result.returncode, 1)
                self.assertIn("nodes[0].sddl", result.stderr)
                self.assertNotIn("S-1-12", result.stderr)

    def test_null_empty_and_missing_dacl_are_distinct(self) -> None:
        for sddl in ("O:SYG:SY", "O:SYG:SYD:", "O:SYG:SYD:NO_ACCESS_CONTROL"):
            with self.subTest(sddl=sddl):
                copied = self.copied()
                copied["nodes"][0]["sddl"] = sddl
                self.assertEqual(self.compare(copied, TREE).returncode, 1)

    def test_only_dacl_control_flags_are_normalized(self) -> None:
        for suffix in (
            "S:AI(AU;SA;FA;;;SY)",
            '(XA;;FR;;;WD;(@User.Label == "D:AI"))',
        ):
            with self.subTest(suffix=suffix):
                original = deepcopy(TREE)
                original["nodes"][0]["sddl"] += suffix
                copied = deepcopy(original)
                copied["nodes"][0]["sddl"] = copied["nodes"][0]["sddl"].replace("D:", "D:AI", 1)
                result = self.compare(copied, original)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    json.loads(result.stdout)["observed"]["nodes"][0]["sddl"],
                    original["nodes"][0]["sddl"],
                )
                copied["nodes"][0]["sddl"] = copied["nodes"][0]["sddl"].replace(suffix, "")
                self.assertEqual(self.compare(copied, original).returncode, 1)

    def test_other_metadata_differences_are_reported_without_values(self) -> None:
        for key, value in (
            ("hash", "do-not-disclose"), ("attributes", 34), ("created", 1),
            ("written", 2), ("relative", "child"), ("kind", "directory"),
            ("sacl", "different"),
        ):
            with self.subTest(key=key):
                copied = self.copied()
                copied["nodes"][0][key] = value
                result = self.compare(copied, TREE)
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"nodes[0].{key}", result.stderr)
                self.assertNotIn("do-not-disclose", result.stderr)

    def test_tree_shape_differences_are_reported(self) -> None:
        for changed, field in (
            ({"kind": "absent", "nodes": []}, "nodes.Count"),
            (TREE | {"kind": "directory"}, "kind"),
        ):
            with self.subTest(field=field):
                result = self.compare(changed, TREE)
                self.assertEqual(result.returncode, 1)
                self.assertIn(field, result.stderr)

    def test_directory_children_and_absence(self) -> None:
        directory = deepcopy(TREE)
        directory["kind"] = "directory"
        directory["nodes"][0]["kind"] = "directory"
        directory["nodes"].append(TREE["nodes"][0] | {"relative": "uv.exe"})
        copied = deepcopy(directory)
        for node in copied["nodes"]:
            node["sddl"] = node["sddl"].replace("D:", "D:AI")
        result = self.compare(copied, directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        absent = {"kind": "absent", "nodes": []}
        self.assertEqual(self.compare(absent, absent).returncode, 0)


if __name__ == "__main__":
    unittest.main()
