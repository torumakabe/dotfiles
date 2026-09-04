"""Verify Copilot hooks run through the directly installed uv on every shell."""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOKS_PATH = REPO_ROOT / "home/private_dot_copilot/hooks/hooks.json"
EXPECTED_PREFIX = "uv run "


def _commands() -> list[dict[str, object]]:
    hooks = json.loads(HOOKS_PATH.read_text(encoding="utf-8"))["hooks"]
    return [command for commands in hooks.values() for command in commands]


class CopilotHooksConfigTests(unittest.TestCase):
    def test_all_commands_start_with_uv_run(self) -> None:
        commands = _commands()
        self.assertEqual(len(commands), 5)

        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(command["bash"].startswith(EXPECTED_PREFIX))
                self.assertTrue(command["powershell"].startswith(EXPECTED_PREFIX))

    def test_no_command_forces_mise_resolution(self) -> None:
        """uv は mise の管理外になったため、解決対象を絞る env は不要である。"""
        for command in _commands():
            with self.subTest(command=command):
                self.assertNotIn("MISE_ENABLE_TOOLS", command["bash"])
                self.assertNotIn("MISE_ENABLE_TOOLS", command["powershell"])

    def test_all_commands_run_from_repository_root(self) -> None:
        for command in _commands():
            with self.subTest(command=command):
                self.assertEqual(command["cwd"], ".")

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    @unittest.skipIf(os.name == "nt", "the POSIX stub requires a POSIX shell")
    def test_bash_invokes_the_uv_on_path_without_extra_environment(self) -> None:
        command = _commands()[0]["bash"]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            capture = root / "capture.txt"
            stub = root / "uv"
            stub.write_text(
                '#!/bin/sh\nprintf "%s" "$*" > "$HOOK_ARGS_CAPTURE"\n',
                encoding="utf-8",
            )
            stub.chmod(0o755)
            env = dict(os.environ)
            env["HOOK_ARGS_CAPTURE"] = str(capture)
            env["HOME"] = str(root)
            env["PATH"] = f"{root}{os.pathsep}{env['PATH']}"

            result = subprocess.run(
                ["bash", "-c", command],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            self.assertEqual(
                capture.read_text(encoding="utf-8"),
                f"run {root}/.copilot/hooks/scripts/copilot-guard.py",
            )

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_invokes_the_uv_on_path_without_extra_environment(self) -> None:
        command = _commands()[0]["powershell"]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            capture = root / "capture.txt"
            stub = root / "uv.ps1"
            stub.write_text(
                "Set-Content -NoNewline -LiteralPath "
                "$env:HOOK_ARGS_CAPTURE -Value ($args -join ' ')\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["HOOK_ARGS_CAPTURE"] = str(capture)
            env["HOME"] = str(root)
            env["PATH"] = f"{root}{os.pathsep}{env['PATH']}"

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            captured = capture.read_text(encoding="utf-8")
            self.assertTrue(captured.startswith("run "), captured)
            self.assertIn("copilot-guard.py", captured)
