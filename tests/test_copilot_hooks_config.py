"""Verify Copilot hooks invoke the resolved uv executable on every shell."""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from tests._helpers import run_hook


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOKS_PATH = REPO_ROOT / "home/private_dot_copilot/hooks/hooks.json"
HOOK_SCRIPTS = REPO_ROOT / "home/private_dot_copilot/hooks/scripts"
UV_ENFORCER_PATH = HOOK_SCRIPTS / "executable_uv-enforcer.py"
COPILOT_GUARD_PATH = HOOK_SCRIPTS / "executable_copilot-guard.py"
EXPECTED_BASH_PREFIX = "uv run "
EXPECTED_POWERSHELL_PREFIX = "uv run "


def _commands() -> list[dict[str, object]]:
    hooks = json.loads(HOOKS_PATH.read_text(encoding="utf-8"))["hooks"]
    return [command for commands in hooks.values() for command in commands]


class CopilotHooksConfigTests(unittest.TestCase):
    def test_cache_mutation_runs_after_enforcers_and_guard(self) -> None:
        pre_tool_use = json.loads(HOOKS_PATH.read_text(encoding="utf-8"))["hooks"][
            "preToolUse"
        ]
        self.assertIn("node-global-enforcer.py", pre_tool_use[0]["bash"])
        self.assertIn("copilot-guard.py", pre_tool_use[1]["bash"])
        self.assertIn("uv-enforcer.py", pre_tool_use[2]["bash"])

    def test_guard_checks_original_command_before_cache_mutation(self) -> None:
        for tool_name in ("bash", "powershell"):
            with self.subTest(tool_name=tool_name):
                payload = {
                    "toolName": tool_name,
                    "toolArgs": {"command": "git commit -m test"},
                }
                guarded = run_hook(
                    COPILOT_GUARD_PATH,
                    payload,
                    cwd=REPO_ROOT,
                )
                self.assertEqual(guarded.returncode, 0, guarded.stderr)
                decision = json.loads(guarded.stdout)
                self.assertEqual(decision["permissionDecision"], "ask")
                self.assertIn("git commit", decision["permissionDecisionReason"])

                mutation = run_hook(UV_ENFORCER_PATH, payload, cwd=REPO_ROOT)
                self.assertEqual(mutation.returncode, 0, mutation.stderr)
                self.assertIn("modifiedArgs", json.loads(mutation.stdout))

    def test_guard_denies_environment_dump_before_cache_mutation(self) -> None:
        for tool_name in ("bash", "powershell"):
            for command in ("printenv", "env"):
                with self.subTest(tool_name=tool_name, command=command):
                    guarded = run_hook(
                        COPILOT_GUARD_PATH,
                        {
                            "toolName": tool_name,
                            "toolArgs": {"command": command},
                        },
                        cwd=REPO_ROOT,
                    )
                    self.assertEqual(guarded.returncode, 0, guarded.stderr)
                    decision = json.loads(guarded.stdout)
                    self.assertEqual(decision["permissionDecision"], "deny")
                    self.assertIn(
                        "env dump",
                        decision["permissionDecisionReason"],
                    )

    def test_guard_allows_safe_command_before_cache_mutation(self) -> None:
        for tool_name, command in (
            ("bash", "printf ok"),
            ("powershell", "Write-Output ok"),
        ):
            with self.subTest(tool_name=tool_name):
                guarded = run_hook(
                    COPILOT_GUARD_PATH,
                    {
                        "toolName": tool_name,
                        "toolArgs": {"command": command},
                    },
                    cwd=REPO_ROOT,
                )
                self.assertEqual(guarded.returncode, 0, guarded.stderr)
                self.assertEqual(guarded.stdout.strip(), "")

                mutation = run_hook(
                    UV_ENFORCER_PATH,
                    {
                        "toolName": tool_name,
                        "toolArgs": {"command": command},
                    },
                    cwd=REPO_ROOT,
                )
                self.assertEqual(mutation.returncode, 0, mutation.stderr)
                self.assertIn("modifiedArgs", json.loads(mutation.stdout))

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
    def test_bash_preserves_cwd_stdin_and_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            capture = root / "capture.txt"
            stub = root / "uv"
            stub.write_text(
                '#!/bin/sh\n'
                '{ printf "%s\\n" "$PWD" "$@"; cat; }'
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
                            lines[:2],
                            [str(root.resolve()), "run"],
                        )
                        expected_script = command["bash"].split('"')[1].replace(
                            "$HOME", env["HOME"]
                        )
                        self.assertEqual(lines[2], expected_script)
                        self.assertEqual(lines[3:], ['{"toolName":"test"}'])

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_preserves_cwd_stdin_and_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            capture = root / "capture.txt"
            stub = root / "uv.ps1"
            stub.write_text(
                "@((Get-Location).Path) + @($args) + "
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
                        self.assertEqual(lines[0], str(root.resolve()))
                        self.assertEqual(lines[1], "run")
                        script_name = command["powershell"].rsplit("\\", 1)[1][:-1]
                        self.assertTrue(
                            lines[2].endswith("\\.copilot\\hooks\\scripts\\" + script_name)
                        )
                        self.assertEqual(lines[3:], ['{"toolName":"test"}'])
