"""Verify mise backend configuration and migration instructions stay aligned."""

import pathlib
import re
import tomllib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "home/dot_config/mise/config.toml.tmpl"
LOCK_PATH = REPO_ROOT / "home/dot_config/mise/private_mise.lock"
INSTRUCTIONS_PATH = REPO_ROOT / ".github/copilot-instructions.md"
SYNC_SH_PATH = REPO_ROOT / "home/run_onchange_after_15-mise-sync-tools.sh.tmpl"
SYNC_PS1_PATH = REPO_ROOT / "home/run_onchange_after_15-mise-sync-tools.ps1.tmpl"


def _tool_alias(config: str, tool: str) -> str:
    match = re.search(
        rf"(?ms)^\[tool_alias\]\s*$.*?^{re.escape(tool)}\s*=\s*\"([^\"]+)\"\s*$",
        config,
    )
    if match is None:
        raise AssertionError(f"Missing [tool_alias] entry for {tool}")
    return match.group(1)


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


if __name__ == "__main__":
    unittest.main()
