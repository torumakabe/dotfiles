"""Verify mise backend configuration and migration instructions stay aligned."""

import pathlib
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "home/dot_config/mise/config.toml.tmpl"
LOCK_PATH = REPO_ROOT / "home/dot_config/mise/private_mise.lock"
INSTRUCTIONS_PATH = REPO_ROOT / ".github/copilot-instructions.md"
SYNC_SH_PATH = REPO_ROOT / "home/run_onchange_after_15-mise-sync-tools.sh.tmpl"
SYNC_PS1_PATH = REPO_ROOT / "home/run_onchange_after_15-mise-sync-tools.ps1.tmpl"
ZSHRC_PATH = REPO_ROOT / "home/dot_zshrc.tmpl"


def _tool_alias(config: str, tool: str) -> str:
    match = re.search(
        rf"(?ms)^\[tool_alias\]\s*$.*?^{re.escape(tool)}\s*=\s*\"([^\"]+)\"\s*$",
        config,
    )
    if match is None:
        raise AssertionError(f"Missing [tool_alias] entry for {tool}")
    return match.group(1)


def _mise_warning_helpers() -> str:
    zshrc = ZSHRC_PATH.read_text(encoding="utf-8")
    start = zshrc.index("_mise_normalize_log_line() {")
    end = zshrc.index("mise-upgrade() {")
    return zshrc[start:end]


class MiseConfigTests(unittest.TestCase):
    def test_dotnet_alias_matches_lock_backend(self) -> None:
        config = CONFIG_PATH.read_text(encoding="utf-8")
        lock = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))

        dotnet_entries = lock["tools"]["dotnet"]
        self.assertEqual(len(dotnet_entries), 1)
        self.assertEqual(_tool_alias(config, "dotnet"), dotnet_entries[0]["backend"])

    def test_backend_migration_requires_postconditions(self) -> None:
        instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")

        for command in ("mise ls <tool>", "mise which <tool>", "<tool> --version"):
            with self.subTest(command=command):
                self.assertIn(command, instructions)
        self.assertIn("`missing` を表示しない", instructions)
        self.assertIn("backend 固有の install path", instructions)

    def test_lock_sync_propagates_mise_failure(self) -> None:
        shell_script = SYNC_SH_PATH.read_text(encoding="utf-8")
        powershell_script = SYNC_PS1_PATH.read_text(encoding="utf-8")

        self.assertIn('exit "$sync_exit"', shell_script)
        self.assertIn("exit $syncExit", powershell_script)
        for script in (shell_script, powershell_script):
            self.assertIn("chezmoi apply", script)
            self.assertNotIn("chezmoi apply --force", script)
            self.assertNotIn("次回 chezmoi apply 時に再試行", script)

    def _check_mise_warnings(self, log: str) -> subprocess.CompletedProcess[str]:
        if shutil.which("zsh") is None:
            self.skipTest("zsh is required for mise warning tests")

        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as log_file:
            log_file.write(log)
            log_file.flush()
            script = (
                _mise_warning_helpers()
                + '\n_mise_check_warnings "$1" "mise upgrade"\n'
            )
            return subprocess.run(
                ["zsh", "-c", script, "mise-warning-test", log_file.name],
                check=False,
                capture_output=True,
                text=True,
            )

    def test_mise_upgrade_allows_minimum_release_age_warning(self) -> None:
        warning = (
            "mise WARN  newer codex release 0.145.0 ignored by "
            "minimum_release_age (24h); latest eligible release is 0.144.6"
        )

        result = self._check_mise_warnings(f"{warning}\n")

        self.assertEqual(result.returncode, 0)
        self.assertIn("処理を継続します", result.stderr)
        self.assertIn(warning, result.stderr)

    def test_mise_upgrade_rejects_unknown_warning(self) -> None:
        warning = "mise WARN missing: uv@0.11.30"

        result = self._check_mise_warnings(f"{warning}\n")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("処理を中止する警告", result.stderr)
        self.assertIn(warning, result.stderr)

    def test_mise_upgrade_strips_ansi_before_warning_check(self) -> None:
        warning = (
            "mise WARN  newer codex release 0.145.0 ignored by "
            "minimum_release_age (24h); latest eligible release is 0.144.6"
        )

        result = self._check_mise_warnings(f"\x1b[33m{warning}\x1b[0m\n")

        self.assertEqual(result.returncode, 0)
        self.assertIn(warning, result.stderr)
        self.assertNotIn("\x1b", result.stderr)

    def test_mise_upgrade_rejects_mixed_warnings(self) -> None:
        allowed = (
            "mise WARN  newer codex release 0.145.0 ignored by "
            "minimum_release_age (24h); latest eligible release is 0.144.6"
        )
        unknown = "mise WARN failed to verify tool metadata"

        result = self._check_mise_warnings(f"{allowed}\n{unknown}\n")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(allowed, result.stderr)
        self.assertIn(unknown, result.stderr)

    def test_mise_upgrade_rejects_extended_allowed_warning(self) -> None:
        warning = (
            "mise WARN  newer codex release 0.145.0 ignored by "
            "minimum_release_age (24h); latest eligible release is 0.144.6; "
            "checksum verification failed"
        )

        result = self._check_mise_warnings(f"{warning}\n")

        self.assertNotEqual(result.returncode, 0)

    def test_mise_upgrade_backs_up_lockfile_before_upgrade(self) -> None:
        zshrc = ZSHRC_PATH.read_text(encoding="utf-8")
        function = zshrc[zshrc.index("mise-upgrade() {") :]

        self.assertLess(
            function.index('command cp -p "$lockfile" "$lock_backup"'),
            function.index('GITHUB_TOKEN="$token" mise upgrade'),
        )
        self.assertIn("emulate -L zsh", function)
        self.assertNotIn("grep -q 'mise WARN'", function)

    def test_mise_upgrade_helpers_use_local_zsh_options(self) -> None:
        helpers = _mise_warning_helpers()

        self.assertEqual(helpers.count("emulate -L zsh"), 4)


if __name__ == "__main__":
    unittest.main()
