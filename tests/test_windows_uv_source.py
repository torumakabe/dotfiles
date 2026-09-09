"""Check the host handoff's Git identity without executing top-level Prepare."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "tests/manual/windows-uv/windows-uv.ps1"
PWSH = os.environ.get("PWSH") or shutil.which("pwsh")
HARNESS = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
foreach ($file in @('uv-state.ps1','windows-uv.ps1')) {
    $tokens=$null; $errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $env:TEST_ENTRY $file),[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
    foreach ($node in $ast.FindAll({
        param($n)
        $n -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $n.Name -in @('Invoke-Captured','Get-SourceCommit','Assert-MiseEnvironment',
            'ConvertTo-WindowsPath','Assert-Path')
    },$true)) {
        . ([scriptblock]::Create($node.Extent.Text))
    }
}
try {
    if ($env:TEST_MODE -eq 'path') {
        $path = ConvertTo-WindowsPath $env:TEST_PATH
        if ($env:TEST_REJECT_PATH) {
            function Get-Item { throw 'Unexpected filesystem lookup' }
            Assert-Path $path
        }
        @{path=$path} | ConvertTo-Json -Compress
    } elseif ($env:TEST_MODE -eq 'environment') {
        if ($env:TEST_ENV_NAME) {
            [Environment]::SetEnvironmentVariable($env:TEST_ENV_NAME,$env:TEST_ENV_VALUE)
        }
        Assert-MiseEnvironment
        @{accepted=$true} | ConvertTo-Json -Compress
    } else {
        if ($env:TEST_GIT_DIR) { $env:GIT_DIR=$env:TEST_GIT_DIR }
        $commit=Get-SourceCommit $env:TEST_SOURCE $env:TEST_COMMIT
        @{sourceCommit=$commit} | ConvertTo-Json -Compress
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""


@unittest.skipUnless(PWSH and shutil.which("git"), "pwsh and git are required")
class WindowsUvSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix=".windows-uv-source-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "source with spaces"
        self.repo.mkdir()
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.upper().startswith(("GIT_", "MISE_", "__MISE_", "TEST_"))
        }
        self.env.update({
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "HOME": str(self.root), "XDG_CONFIG_HOME": str(self.root),
            "TEST_ENTRY": str(ENTRY.parent), "TEST_SOURCE": str(self.repo),
        })
        self.git("init", "--quiet")
        (self.repo / "tracked.txt").write_text("original\n", encoding="utf-8")
        fixture = self.repo / "tests/manual/windows-uv"
        fixture.mkdir(parents=True)
        shutil.copyfile(ENTRY.parent / ".gitignore", fixture / ".gitignore")
        self.git("add", ".")
        self.commit()
        self.sha = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-c", "core.hooksPath=" + str(self.root / "no-hooks"), *args],
            cwd=self.repo, env=self.env, capture_output=True, text=True, check=True,
        )

    def commit(self) -> None:
        self.git(
            "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture",
        )

    def identify(self, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", HARNESS],
            cwd=self.root, env=self.env | {"TEST_COMMIT": self.sha} | env,
            capture_output=True, text=True, check=False,
        )

    def assert_rejected(self, message: str, **env: str) -> None:
        result = self.identify(**env)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(message, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_identifies_clean_root_and_normalizes_sha(self) -> None:
        result = self.identify(TEST_COMMIT=self.sha.upper())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"sourceCommit": self.sha})
        self.assertEqual(self.git("status", "--porcelain").stdout, "")

    def test_missing_or_bad_commit(self) -> None:
        for value in ("", self.sha[:12], "g" * 40, self.sha + "0"):
            with self.subTest(value=value):
                self.assert_rejected("40-hex SourceCommit", TEST_COMMIT=value)

    def test_different_head(self) -> None:
        (self.repo / "tracked.txt").write_text("new commit\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        self.commit()
        self.assert_rejected("HEAD does not match")

    def test_modified_tracked_file(self) -> None:
        (self.repo / "tracked.txt").write_text("modified\n", encoding="utf-8")
        self.assert_rejected("tracked or untracked changes")

    def test_staged_tracked_file(self) -> None:
        (self.repo / "tracked.txt").write_text("staged\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        self.assert_rejected("tracked or untracked changes")

    def test_unexpected_untracked_file(self) -> None:
        (self.repo / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        self.assert_rejected("tracked or untracked changes")

    def test_subdirectory_is_not_source_root(self) -> None:
        self.assert_rejected("worktree root", TEST_SOURCE=str(self.repo / "tests"))

    def test_non_repository_is_rejected(self) -> None:
        # Disable discovery of the enclosing project, without modifying its config.
        self.assert_rejected(
            "Child failed", TEST_SOURCE=str(self.root),
            GIT_CEILING_DIRECTORIES=str(ROOT),
        )

    def test_ignored_native_evidence_is_retained(self) -> None:
        evidence = self.repo / "tests/manual/windows-uv/native-result-08/result.json"
        evidence.parent.mkdir()
        evidence.write_text('{"retained":true}', encoding="utf-8")
        result = self.identify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["sourceCommit"], self.sha)
        self.assertEqual(evidence.read_text(encoding="utf-8"), '{"retained":true}')

    def test_git_directory_override_is_rejected(self) -> None:
        self.assert_rejected("GIT_DIR overrides", TEST_GIT_DIR=str(self.repo / ".git"))

    def test_recheck_rejects_later_edits(self) -> None:
        self.assertEqual(self.identify().returncode, 0)
        (self.repo / "tracked.txt").write_text("concurrent\n", encoding="utf-8")
        self.assert_rejected("tracked or untracked changes")

    def test_official_pwsh_marker_is_allowed(self) -> None:
        for env in ({}, {"TEST_ENV_NAME": "MISE_SHELL", "TEST_ENV_VALUE": "pwsh"}):
            with self.subTest(env=env):
                result = self.identify(TEST_MODE="environment", **env)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_overrides_remain_rejected(self) -> None:
        for name, value in (
            ("MISE_GLOBAL_CONFIG_FILE", "other.toml"), ("MISE_CONFIG_DIR", "other"),
            ("MISE_DATA_DIR", "other"), ("MISE_CACHE_DIR", "other"),
            ("MISE_STATE_DIR", "other"), ("MISE_ENV", "production"),
            ("MISE_UNKNOWN", "1"), ("MISE_SHELL", "unexpected"),
        ):
            with self.subTest(name=name):
                self.assert_rejected(
                    f"Existing {name} override", TEST_MODE="environment",
                    TEST_ENV_NAME=name, TEST_ENV_VALUE=value,
                )

    def test_source_checks_bracket_prepare_only(self) -> None:
        text = ENTRY.read_text(encoding="utf-8")
        prepare = text.split("if ($Command -eq 'Prepare') {", 1)[1]
        prepare, saved = prepare.split("if (-not $SnapshotDigest", 1)
        self.assertLess(
            prepare.index("Get-SourceCommit $Source $SourceCommit"),
            prepare.index("New-Directory $Backup"),
        )
        self.assertIn("sourceCommit=$verifiedCommit", prepare)
        self.assertLess(
            prepare.index("Get-SourceCommit $Source $verifiedCommit"),
            prepare.index("Write-NewJson (Join-Path $Backup 'snapshot.json')"),
        )
        self.assertNotIn("Get-SourceCommit", saved)
        self.assertNotIn("$SourceCommit", saved)
        self.assertNotIn("candidate-manifest", text)

    def test_mise_path_separators_are_normalized(self) -> None:
        expected = r"C:\Users\tomakabe\.config\mise\config.toml"
        for path in (
            expected, "C:/Users/tomakabe/.config/mise/config.toml",
            r"C:\Users\tomakabe\.config/mise/config.toml",
            r"C:\\Users\\tomakabe\\\.config/mise/config.toml",
        ):
            with self.subTest(path=path):
                result = self.identify(TEST_MODE="path", TEST_PATH=path)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {"path": expected})

    def test_normalization_preserves_valid_path_components(self) -> None:
        for path, expected in (
            ("C:/Users/First Last/.config/mise/config.toml",
             r"C:\Users\First Last\.config\mise\config.toml"),
            ("D:/", "D:\\"),
        ):
            with self.subTest(path=path):
                result = self.identify(TEST_MODE="path", TEST_PATH=path)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {"path": expected})

    def test_non_local_or_relative_paths_are_not_reinterpreted(self) -> None:
        for path in (
            "", "config.toml", "C:config.toml", "/config.toml",
            r"\\server\share\config.toml", "//server/share/config.toml",
            r"\\?\C:\config.toml", r"\\.\C:\config.toml",
        ):
            with self.subTest(path=path):
                self.assert_rejected(
                    "Unsupported local absolute path", TEST_MODE="path", TEST_PATH=path,
                )

    def test_normalization_does_not_bypass_lexical_rejections(self) -> None:
        for path in (
            "C:/Users/../config.toml", "C:/Users/./config.toml",
            "C:/Users/config.toml:stream", "C:/Users /config.toml",
            "C:/Users./config.toml", "C:/Users/config.toml ",
            "C:/Users/CON.txt", "C:/Users/NUl/config.toml",
            "C:/Users/*.toml", 'C:/Users/"config.toml',
        ):
            with self.subTest(path=path):
                self.assert_rejected(
                    "Unsupported local absolute path", TEST_MODE="path",
                    TEST_PATH=path, TEST_REJECT_PATH="1",
                )

    def test_path_normalization_covers_input_and_mise_queries(self) -> None:
        text = ENTRY.read_text(encoding="utf-8")
        prepare = text.split("if ($Command -eq 'Prepare') {", 1)[1]
        for name in ("Config", "Data", "Cache", "Source"):
            self.assertLess(
                prepare.index(f"${name} = ConvertTo-WindowsPath ${name}"),
                prepare.index("foreach ($path in @($Config,$Data,$Cache,$Source))"),
            )
        for name in ("activeConfigs", "configs"):
            self.assertIn(
                f"@(${name} | ForEach-Object {{ ConvertTo-WindowsPath $_.path }})", text,
            )
        for name in ("where", "activeCache", "exe"):
            self.assertRegex(text, rf"\${name}\s*=\s*ConvertTo-WindowsPath")


if __name__ == "__main__":
    unittest.main()
