"""Verify Copilot hooks isolate mise resolution to uv on every shell."""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOKS_PATH = REPO_ROOT / "home/private_dot_copilot/hooks/hooks.json"
EXPECTED_BASH_PREFIX = "MISE_ENABLE_TOOLS=uv uv run "
EXPECTED_POWERSHELL_PREFIX = "$env:MISE_ENABLE_TOOLS='uv'; uv run "


def _commands() -> list[dict[str, object]]:
    hooks = json.loads(HOOKS_PATH.read_text(encoding="utf-8"))["hooks"]
    return [command for commands in hooks.values() for command in commands]


class CopilotHooksConfigTests(unittest.TestCase):
    def test_all_commands_limit_mise_to_uv(self) -> None:
        commands = _commands()
        self.assertEqual(len(commands), 5)

        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(command["bash"].startswith(EXPECTED_BASH_PREFIX))
                self.assertTrue(
                    command["powershell"].startswith(EXPECTED_POWERSHELL_PREFIX)
                )

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    @unittest.skipIf(os.name == "nt", "the POSIX stub requires a POSIX shell")
    def test_bash_exports_uv_allowlist_to_hook_process(self) -> None:
        command = _commands()[0]["bash"]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            capture = root / "capture.txt"
            stub = root / "uv"
            stub.write_text(
                '#!/bin/sh\nprintf "%s" "$MISE_ENABLE_TOOLS" > "$HOOK_ENV_CAPTURE"\n',
                encoding="utf-8",
            )
            stub.chmod(0o755)
            env = dict(os.environ)
            env["HOOK_ENV_CAPTURE"] = str(capture)
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
            self.assertEqual(capture.read_text(encoding="utf-8"), "uv")

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_exports_uv_allowlist_to_hook_process(self) -> None:
        command = _commands()[0]["powershell"]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            capture = root / "capture.txt"
            stub = root / "uv.ps1"
            stub.write_text(
                "Set-Content -NoNewline -LiteralPath "
                "$env:HOOK_ENV_CAPTURE -Value $env:MISE_ENABLE_TOOLS\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["HOOK_ENV_CAPTURE"] = str(capture)
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
            self.assertEqual(capture.read_text(encoding="utf-8"), "uv")
