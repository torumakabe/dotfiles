"""Verify Copilot hooks invoke the resolved uv executable on every shell."""

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
    def test_all_commands_invoke_uv_directly(self) -> None:
        commands = _commands()
        self.assertEqual(len(commands), 5)

        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(command["bash"].startswith(EXPECTED_BASH_PREFIX))
                self.assertTrue(
                    command["powershell"].startswith(EXPECTED_POWERSHELL_PREFIX)
                )
                self.assertNotIn("mise exec", command["bash"])
                self.assertNotIn("mise exec", command["powershell"])

    def test_all_commands_run_from_repository_root(self) -> None:
        for command in _commands():
            with self.subTest(command=command):
                self.assertEqual(command["cwd"], ".")

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    @unittest.skipIf(os.name == "nt", "the POSIX stub requires a POSIX shell")
    def test_bash_exports_uv_allowlist_to_hook_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            capture = root / "capture.txt"
            stub = root / "uv"
            stub.write_text(
                '#!/bin/sh\n'
                '{ printf "%s\\n" "$MISE_ENABLE_TOOLS" "$PWD" "$@"; cat; }'
                ' > "$HOOK_ENV_CAPTURE"\nexit "${HOOK_EXIT_CODE:-0}"\n',
                encoding="utf-8",
            )
            stub.chmod(0o755)
            env = dict(os.environ)
            env["HOOK_ENV_CAPTURE"] = str(capture)
            env["PATH"] = f"{root}{os.pathsep}{env['PATH']}"
            env["HOME"] = str(root / "home with spaces")

            for command in _commands():
                for exit_code in (0, 23):
                    with self.subTest(command=command["bash"], exit_code=exit_code):
                        env["HOOK_EXIT_CODE"] = str(exit_code)
                        result = subprocess.run(
                            ["bash", "--noprofile", "--norc", "-c", command["bash"]],
                            input='{"toolName":"test"}\n',
                            cwd=root,
                            check=False,
                            capture_output=True,
                            text=True,
                            env=env,
                        )
                        self.assertEqual(result.returncode, exit_code, result.stderr)
                        self.assertEqual(result.stdout, "")
                        lines = capture.read_text(encoding="utf-8").splitlines()
                        self.assertEqual(
                            lines[:3],
                            ["uv", str(root.resolve()), "run"],
                        )
                        expected_script = command["bash"].split('"')[1].replace(
                            "$HOME", env["HOME"]
                        )
                        self.assertEqual(lines[3], expected_script)
                        self.assertEqual(lines[4:], ['{"toolName":"test"}'])

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_exports_uv_allowlist_to_hook_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            capture = root / "capture.txt"
            stub = root / "uv.ps1"
            stub.write_text(
                "@($env:MISE_ENABLE_TOOLS, (Get-Location).Path) + @($args) + "
                "@([Console]::In.ReadToEnd().TrimEnd()) | "
                "Set-Content -LiteralPath $env:HOOK_ENV_CAPTURE\n"
                "exit ([int]$env:HOOK_EXIT_CODE)\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["HOOK_ENV_CAPTURE"] = str(capture)
            env["PATH"] = f"{root}{os.pathsep}{env['PATH']}"

            for command in _commands():
                for exit_code in (0, 23):
                    with self.subTest(command=command["powershell"], exit_code=exit_code):
                        env["HOOK_EXIT_CODE"] = str(exit_code)
                        result = subprocess.run(
                            ["pwsh", "-NoProfile", "-Command", command["powershell"]],
                            input='{"toolName":"test"}\n',
                            cwd=root,
                            check=False,
                            capture_output=True,
                            text=True,
                            env=env,
                        )
                        # pwsh -Command maps a failing native/script command to 1.
                        self.assertEqual(
                            result.returncode, 0 if exit_code == 0 else 1,
                            result.stderr,
                        )
                        self.assertEqual(result.stdout, "")
                        lines = capture.read_text(encoding="utf-8-sig").splitlines()
                        self.assertEqual(lines[:2], ["uv", str(root.resolve())])
                        self.assertEqual(lines[2], "run")
                        script_name = command["powershell"].rsplit("\\", 1)[1][:-1]
                        self.assertTrue(
                            lines[3].endswith("\\.copilot\\hooks\\scripts\\" + script_name)
                        )
                        self.assertEqual(lines[4:], ['{"toolName":"test"}'])
