"""Exercise isolated config discovery with an existing mise, not an installer."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_windows_uv_source import ENTRY, HARNESS, PWSH, ROOT


MISE = os.environ.get("TEST_MISE") or shutil.which("mise")


@unittest.skipUnless(PWSH and MISE, "existing pwsh and mise are required")
class WindowsUvConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".windows-uv-config-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.backup = self.home / "windows-uv-fixture"
        self.work = self.backup / "work"
        self.global_config = self.home / ".config/mise/config.toml"
        self.candidate_config = self.work / "config/config.toml"
        for path in (self.global_config, self.candidate_config):
            path.parent.mkdir(parents=True)
            path.write_text("[tools]\n", encoding="utf-8")
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.upper().startswith(("MISE_", "__MISE_", "TEST_", "GIT_"))
            and key.upper() not in ("GH_TOKEN", "GITHUB_TOKEN")
        }
        self.env.update({
            "HOME": str(self.home), "USERPROFILE": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "MISE_CEILING_PATHS": self.temp.name,
            "TEST_ENTRY": str(ENTRY.parent), "TEST_MODE": "isolated-env",
            "TEST_BACKUP": str(self.backup),
        })
        result = subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", HARNESS],
            cwd=self.work, env=self.env, capture_output=True, text=True, check=True,
        )
        self.isolated = json.loads(result.stdout)
        # Keep the real machine's system configuration out of the fixture.
        self.isolated["MISE_SYSTEM_CONFIG_FILE"] = str(self.home / "no-system-config.toml")

    def config_paths(self, environment):
        before = {
            p: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in (self.global_config, self.candidate_config)
        }
        result = subprocess.run(
            [MISE, "config", "ls", "--json"], cwd=self.work,
            env=self.env | environment, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for path, unchanged in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), unchanged)
        return [Path(item["path"]) for item in json.loads(result.stdout)]

    def test_global_file_override_alone_still_discovers_ancestor_home_config(self):
        legacy = self.isolated.copy()
        del legacy["MISE_CONFIG_DIR"]
        del legacy["MISE_CEILING_PATHS"]
        self.assertEqual(
            set(self.config_paths(legacy)), {self.global_config, self.candidate_config},
        )

    def test_config_directory_override_excludes_home_config(self):
        self.assertEqual(Path(self.isolated["MISE_CONFIG_DIR"]), self.candidate_config.parent)
        self.assertEqual(Path(self.isolated["MISE_CEILING_PATHS"]), self.backup)
        self.assertEqual(self.config_paths(self.isolated), [self.candidate_config])

    def test_other_unexpected_project_config_is_not_silently_hidden(self):
        extra = self.work / "mise.toml"
        extra.write_text("[tools]\n", encoding="utf-8")
        self.assertEqual(
            set(self.config_paths(self.isolated)), {extra, self.candidate_config},
        )

    def test_ancestor_project_configs_are_outside_isolated_scope(self):
        for path in (self.home / "mise.toml", self.backup / "mise.toml"):
            path.write_text("[tools]\n", encoding="utf-8")
        self.assertEqual(self.config_paths(self.isolated), [self.candidate_config])

    def test_prepare_checks_scope_before_using_isolated_tool_config(self):
        text = ENTRY.read_text(encoding="utf-8")
        prepare = text.split("if ($Command -eq 'Prepare') {", 1)[1]
        prepare = prepare.split("if (-not $SnapshotDigest", 1)[0]
        self.assertLess(
            prepare.index("Unexpected additional mise config during Prepare"),
            prepare.index("$oldTool ="),
        )
        self.assertLess(
            prepare.index("Unexpected additional mise config during Prepare"),
            prepare.index("'config','set'"),
        )
        install = text.split("if ($Command -eq 'Install') {", 1)[1]
        self.assertLess(
            install.index("Unexpected additional mise config"),
            install.index("if ($UseExistingGitHubAuth)"),
        )
        self.assertLess(
            install.index("Unexpected additional mise config"),
            install.index("$journal.phase='install-started'"),
        )


if __name__ == "__main__":
    unittest.main()
