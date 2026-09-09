"""Bounded direct-install inventory: no native installer or home writes."""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest

from test_windows_uv_source import PWSH, ROOT


ENTRY = ROOT / "tests/manual/windows-uv/plan-direct-windows-uv.ps1"
HARNESS = r"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
foreach ($file in @('uv-state.ps1','plan-direct-windows-uv.ps1')) {
    $tokens=$null; $errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $env:TEST_ENTRY $file),[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
    foreach ($node in $ast.FindAll({
        param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]
    },$false)) { . ([scriptblock]::Create($node.Extent.Text)) }
}
$inputValue=Get-Content -LiteralPath $env:TEST_INPUT -Raw | ConvertFrom-Json -AsHashtable
function Read-Tree([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return @{kind='absent';nodes=@()} }
    if (Test-Path -LiteralPath $Path -PathType Container) { return @{kind='directory';nodes=@()} }
    return @{kind='file';nodes=@(@{hash=(Get-Hash $Path)})}
}
function Assert-Path {}
try {
    $result=switch ($env:TEST_MODE) {
        'lock' { Assert-DirectLock $inputValue.original $inputValue.candidate $inputValue.version }
        'aliases' { @(Get-DirectAliasNames $inputValue.versions $inputValue.config) }
        'config' { Get-DirectCandidateConfig $inputValue.original $inputValue.uvDeclaration }
        'environment' {
            foreach ($key in $inputValue.Keys) { Set-Item -LiteralPath "Env:$key" -Value $inputValue[$key] }
            Assert-DirectEnvironment
            @{accepted=$true}
        }
        'clean-source' {
            function Invoke-Captured($Executable, $Arguments, $Directory) {
                if ($Arguments -contains 'status') { return @{stdout=$inputValue.tracked} }
                if ($Arguments -contains 'ls-files') { return @{stdout=$inputValue.untracked} }
                throw 'Unexpected Git operation.'
            }
            Assert-DirectCleanSource 'git' 'source'
            @{accepted=$true}
        }
        'slot' { Get-DirectSlot $inputValue.path $inputValue.versions }
        'destinations' {
            Assert-DirectDestinations $inputValue.protected $inputValue.recovery $inputValue.report
            @{accepted=$true}
        }
        'inventory' {
            Get-DirectInventory $inputValue.installs $inputValue.cache $inputValue.downloads $inputValue.config
        }
        'write-new' {
            Write-NewJson $inputValue.path @{schema=1}
            @{written=$true}
        }
        'fresh-parent' {
            Assert-DirectFreshParent $inputValue.path
            @{accepted=$true}
        }
        default { throw 'Unknown fixture mode.' }
    }
    ConvertTo-Json -InputObject $result -Depth 100 -Compress
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""


@unittest.skipUnless(PWSH, "existing PowerShell required")
class WindowsUvDirectPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".windows-uv-direct-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {
            k: v for k, v in os.environ.items()
            if not k.upper().startswith(("MISE_", "__MISE_", "TEST_", "GIT_"))
        }
        self.env.update(TEST_ENTRY=str(ENTRY.parent), TEST_INPUT=str(self.root / "input.json"))

    def run_mode(self, mode, value, error=None):
        Path(self.env["TEST_INPUT"]).write_text(json.dumps(value), encoding="utf-8")
        result = subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", HARNESS],
            env=self.env | {"TEST_MODE": mode}, cwd=self.root,
            capture_output=True, text=True, check=False,
        )
        if error:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn(error, result.stderr)
            self.assertEqual(result.stdout, "")
            return None
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def locks(self):
        candidate = tomllib.loads((ROOT / "home/dot_config/mise/private_mise.lock").read_text())
        original = copy.deepcopy(candidate)
        for entry in original["tools"]["uv"]:
            entry["backend"] = "aqua:astral-sh/uv"
        return dict(original=original, candidate=candidate, version=candidate["tools"]["uv"][0]["version"])

    def test_current_lock_keeps_same_version_all_five_platforms(self):
        inputs = self.locks()
        result = self.run_mode("lock", inputs)
        self.assertEqual(result, inputs["candidate"])
        self.assertEqual({entry["version"] for entry in result["tools"]["uv"]}, {"0.12.10"})

    def test_single_original_aqua_entry_matches_split_github_options(self):
        inputs = self.locks()
        old = inputs["original"]["tools"]["uv"][0]
        old["platforms.windows-arm64"] = inputs["original"]["tools"]["uv"][1]["platforms.windows-arm64"]
        old["specifiers"] = ["latest"]
        inputs["original"]["tools"]["uv"] = [old]
        result = self.run_mode("lock", inputs)
        self.assertEqual(result, inputs["candidate"])

    def test_config_accepts_registry_default_and_explicit_aqua_without_other_changes(self):
        tools = {name: "latest" for name in self.locks()["original"]["tools"]}
        declaration = {"version": "latest", "platforms": {
            "windows-arm64": {"asset_pattern": "uv-x86_64-pc-windows-msvc.zip"},
        }}
        for aliases in (None, {"dotnet": "core:dotnet"},
                        {"dotnet": "core:dotnet", "uv": "aqua:astral-sh/uv"}):
            with self.subTest(aliases=aliases):
                original = {"tools": tools, "settings": {"lockfile": True}}
                if aliases is not None:
                    original["tool_alias"] = aliases
                result = self.run_mode("config", {"original": original, "uvDeclaration": declaration})
                expected = copy.deepcopy(original)
                expected["tools"]["uv"] = declaration
                expected.setdefault("tool_alias", {})["uv"] = "github:astral-sh/uv"
                self.assertEqual(result, expected)

    def test_config_rejects_another_explicit_backend(self):
        tools = {name: "latest" for name in self.locks()["original"]["tools"]}
        self.run_mode("config", {
            "original": {"tools": tools, "tool_alias": {"uv": "core:uv"}},
            "uvDeclaration": {"version": "latest"},
        }, "Unexpected explicit original uv backend")

    def test_normal_powershell_activation_is_not_an_override(self):
        result = self.run_mode("environment", {
            "MISE_SHELL": "pwsh", "__MISE_ORIG_PATH": "original-path",
            "__MISE_DIFF": "activation-state", "__MISE_SESSION": "session",
        })
        self.assertTrue(result["accepted"])

    def test_source_and_mise_overrides_are_still_rejected(self):
        for name in ("GIT_DIR", "GIT_WORK_TREE", "MISE_DATA_DIR", "MISE_SHIMS_DIR"):
            with self.subTest(name=name):
                self.run_mode("environment", {name: "override"}, "Environment override requires review")

    def test_retained_native_results_do_not_dirty_source(self):
        result = self.run_mode("clean-source", {
            "tracked": "", "untracked": "tests/manual/windows-uv/native-result-08/result.json\r\n",
        })
        self.assertTrue(result["accepted"])

    def test_other_source_changes_are_rejected(self):
        self.run_mode("clean-source", {
            "tracked": " M tests/manual/windows-uv/uv-state.ps1\n", "untracked": "",
        }, "Source has tracked changes")
        for path in ("other.txt", "tests/manual/windows-uv/native-result-08",
                     "tests/manual/windows-uv/native-result-08-extra/result.json"):
            with self.subTest(path=path):
                self.run_mode("clean-source", {
                    "tracked": "", "untracked": path + "\n",
                }, "Source has untracked changes")

    def test_version_is_not_hardcoded_in_entry(self):
        inputs = self.locks()
        inputs["version"] = "7.8.9"
        for lock in (inputs["original"], inputs["candidate"]):
            for entry in lock["tools"]["uv"]:
                entry["version"] = "7.8.9"
        result = self.run_mode("lock", inputs)
        self.assertEqual(result["tools"]["uv"][0]["version"], "7.8.9")
        self.assertNotIn("0.12.10", ENTRY.read_text())

    def test_source_other_tool_changes_are_not_published(self):
        inputs = self.locks()
        inputs["candidate"]["tools"]["node"][0]["version"] = "999.0.0"
        result = self.run_mode("lock", inputs)
        self.assertEqual(result["tools"]["node"], inputs["original"]["tools"]["node"])

    def test_rejects_different_original_version(self):
        inputs = self.locks()
        inputs["original"]["tools"]["uv"][0]["version"] = "0.12.9"
        self.run_mode("lock", inputs, "same requested version on aqua")

    def test_rejects_candidate_aqua_or_wrong_version(self):
        for field, value in (("backend", "aqua:astral-sh/uv"), ("version", "0.12.11")):
            with self.subTest(field=field):
                inputs = self.locks()
                inputs["candidate"]["tools"]["uv"][0][field] = value
                self.run_mode("lock", inputs, "same requested version on GitHub")

    def test_rejects_checksum_or_platform_changes(self):
        inputs = self.locks()
        inputs["candidate"]["tools"]["uv"][0]["platforms.windows-x64"]["checksum"] = "sha256:bad"
        self.run_mode("lock", inputs, "Asset changed")
        inputs = self.locks()
        del inputs["candidate"]["tools"]["uv"][0]["platforms.windows-x64"]
        self.run_mode("lock", inputs, "Unexpected candidate platforms")

    def test_rejects_arm64_override_removal(self):
        inputs = self.locks()
        inputs["candidate"]["tools"]["uv"][1]["options"]["asset_pattern"] = "uv-aarch64.zip"
        self.run_mode("lock", inputs, "Missing Windows ARM64 x64 override")

    def test_rejects_silent_original_platform_removal(self):
        inputs = self.locks()
        inputs["original"]["tools"]["uv"][0]["platforms.linux-s390x"] = {}
        self.run_mode("lock", inputs, "Original platform set differs")

    def test_aliases_include_old_minors_and_custom_names(self):
        result = self.run_mode("aliases", {
            "versions": ["0.11.29", "0.12.9", "0.12.10"],
            "config": {"alias": {"uv": {"stable": "0.12.10"}}},
        })
        self.assertEqual(set(result), {"0", "0.11", "0.12", "latest", "stable"})

    def test_alias_path_escape_is_rejected(self):
        self.run_mode("aliases", {
            "versions": ["0.12.10"], "config": {"alias": {"uv": {"../other": "0.12.10"}}},
        }, "Unsupported custom uv alias")

    def test_slot_directory_is_blocked_and_preserved(self):
        path = self.root / "latest"
        path.mkdir()
        retained = path / "do-not-remove"
        retained.write_text("original")
        result = self.run_mode("slot", {"path": str(path), "versions": ["0.12.10"]})
        self.assertEqual(result["classification"], "blocked_directory")
        self.assertEqual(retained.read_text(), "original")

    def test_slot_candidates_and_unknown_content(self):
        path = self.root / "latest"
        for text, classification in (
            ("0.12.10", "version_pointer_candidate"),
            ("./0.12.10\n", "path_pointer_candidate"),
            (r"C:\Users\fixture\mise\installs\uv\0.12.10", "path_pointer_candidate"),
            ("not-a-pointer-secret", "unresolved_pointer_format"),
            ("a" * 4097, "blocked_nonpointer"),
        ):
            with self.subTest(classification=classification):
                path.write_text(text)
                result = self.run_mode("slot", {"path": str(path), "versions": ["0.12.10"]})
                self.assertEqual(result["classification"], classification)
                if classification == "unresolved_pointer_format":
                    self.assertNotIn(text, json.dumps(result))
                self.assertEqual(path.read_text(), text)

    def test_absent_slot_is_not_created(self):
        path = self.root / "latest"
        result = self.run_mode("slot", {"path": str(path), "versions": ["0.12.10"]})
        self.assertEqual(result["classification"], "absent")
        self.assertFalse(path.exists())

    def test_inventory_keeps_probe_names_outside_scope(self):
        installs = self.root / "installs"
        uv = installs / "uv"
        uv.mkdir(parents=True)
        (uv / "0.11.29").mkdir()
        (uv / "0.12.10").mkdir()
        probe = uv / ".n4-uv-existing"
        probe.mkdir()
        (probe / "unread").write_text("do not inspect")
        (uv / "latest").write_text("0.12.10")
        node = installs / "node"
        node.mkdir()
        (node / ".mise.backend.toml").write_text('backend = "core:node"')
        cache = self.root / "cache"
        cache.mkdir()
        (cache / "uv").mkdir()
        result = self.run_mode("inventory", {
            "installs": str(installs), "cache": str(cache),
            "downloads": str(self.root / "downloads"), "config": {},
        })
        self.assertEqual(result["outsideScopeNames"], [probe.name])
        self.assertEqual(set(result["versions"]), {"0.11.29", "0.12.10"})
        self.assertEqual(result["otherLegacyMetadata"]["node"]["kind"], "file")
        self.assertEqual(result["uvDownloads"]["parentAbsent"], True)
        self.assertNotIn("do not inspect", json.dumps(result))
        self.assertTrue(probe.exists())

    def test_destination_overlap_and_old_report_are_rejected(self):
        inputs = {"protected": [r"C:\home\mise"], "recovery": r"C:\home\new-recovery",
                  "report": r"C:\home\new-report.json"}
        self.assertTrue(self.run_mode("destinations", inputs)["accepted"])
        self.run_mode("destinations", inputs | {"recovery": r"c:\HOME\MISE\backup"}, "overlaps")
        self.run_mode("destinations", inputs | {"report": r"C:\home\new-recovery\plan.json"}, "separate")
        old = self.root / "old-report.json"
        old.write_text("legacy")
        self.run_mode("destinations", inputs | {"report": str(old)}, "must be new")
        self.assertEqual(old.read_text(), "legacy")

    def test_report_creation_is_exclusive(self):
        path = self.root / "plan.json"
        self.run_mode("write-new", {"path": str(path)})
        before = path.read_bytes()
        self.run_mode("write-new", {"path": str(path)}, "already exists")
        self.assertEqual(path.read_bytes(), before)

    def test_new_names_cannot_be_nested_in_legacy_recovery(self):
        old = self.root / "old-recovery"
        nested = old / "nested"
        nested.mkdir(parents=True)
        (old / "journal.json").write_text('{"phase":"restored"}')
        self.run_mode("fresh-parent", {"path": str(nested / "new-report.json")}, "existing recovery")
        self.assertEqual((old / "journal.json").read_text(), '{"phase":"restored"}')
        self.assertTrue(self.run_mode("fresh-parent", {"path": str(self.root / "new-report.json")})["accepted"])


class DirectPlanBoundaryTests(unittest.TestCase):
    def test_only_plan_is_exposed_and_no_mise_or_uv_command_is_invoked(self):
        text = ENTRY.read_text()
        self.assertIn("[ValidateSet('Plan')]", text)
        self.assertNotIn("Invoke-Captured $mise", text)
        self.assertNotIn("Invoke-Captured $exe", text)
        for forbidden in ("Move-Tree ", "Copy-Tree ", "Set-Acl ", "Remove-Item ",
                          "New-ExclusiveDirectory ", "Save-Journal ", "Start-Sleep "):
            self.assertNotIn(forbidden, text)
        self.assertIn("canApply=$false", text)
        self.assertIn("rootsConfirmedByMise=$false", text)

    def test_source_and_inputs_rechecked_before_exclusive_report(self):
        text = ENTRY.read_text()
        self.assertLess(text.rindex("Assert-DirectSource $Source"), text.index("Write-NewJson $Report"))
        self.assertLess(text.index("Input changed during Plan"), text.index("Write-NewJson $Report"))
        self.assertIn("parentAbsent=$true", text)


if __name__ == "__main__":
    unittest.main()
