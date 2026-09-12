import json
import os
import pathlib
import shlex
import sys
import tempfile
import unittest
from unittest import mock

from tests._helpers import load_script, run_hook


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT_PATH = (
    REPO_ROOT
    / "home/private_dot_copilot/hooks/scripts/executable_uv-enforcer.py"
)

uve = load_script("uv_enforcer", SCRIPT_PATH)


class CommandPolicyTests(unittest.TestCase):
    def _assert_commands(self, commands: tuple[str, ...], blocked: bool) -> None:
        for command in commands:
            with self.subTest(command=command):
                result = uve.check_command(command)
                if blocked:
                    self.assertIsNotNone(result)
                else:
                    self.assertIsNone(result)

    def test_blocks_direct_python_and_pip(self) -> None:
        self._assert_commands(
            (
                "python",
                "python script.py",
                "python3 script.py",
                "python3.13 script.py",
                "python3.13.exe script.py",
                "python -m pytest",
                "PYTHONPATH=/foo python script.py",
                "sudo python script.py",
                "sudo -E python3 -m pytest",
                "env python script.py",
                "/usr/bin/python3 script.py",
                "/usr/local/bin/pip install requests",
                "/usr/bin/env python3 script.py",
                "/usr/bin/sudo python3 script.py",
                "sudo -u root python3 script.py",
                "sudo -u nobody pip install requests",
                "env -u PYTHONPATH python3 script.py",
                "command python script.py",
                "command pip install requests",
                "pip install requests",
                "pip3 install requests",
                "pip3.13 install requests",
                "pip3.13.exe install requests",
                "pip freeze",
                "pip list",
            ),
            blocked=True,
        )

    def test_allows_uv_and_unrelated_commands(self) -> None:
        self._assert_commands(
            (
                "uv run python script.py",
                "uv run script.py",
                "uv add requests",
                "uv pip install requests",
                "uv",
                "uv run -m pytest -v",
                "",
                "git status",
                "node script.js",
                "npm install",
            ),
            blocked=False,
        )

    def test_shell_chains(self) -> None:
        cases = (
            ("echo ok && python script.py", True),
            ("echo ok && uv run python script.py", False),
            ("cd /tmp; pip install foo", True),
            ("echo foo | python", True),
            ("uv run script.py && pip install foo", True),
            ("echo ok && pip install foo", True),
        )
        for command, blocked in cases:
            with self.subTest(command=command):
                result = uve.check_command(command)
                self.assertEqual(result is not None, blocked)


class MainIntegrationTests(unittest.TestCase):
    def _decision(self, payload: dict | str) -> dict:
        result = run_hook(SCRIPT_PATH, payload)
        self.assertEqual(result.returncode, 0)
        return json.loads(result.stdout)

    def _assert_allowed(self, payload: dict) -> None:
        result = run_hook(SCRIPT_PATH, payload)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_deny_bare_python(self) -> None:
        output = self._decision(
            {
                "toolName": "bash",
                "toolArgs": {"command": "python script.py"},
            }
        )
        self.assertEqual(output["permissionDecision"], "deny")

    def test_python_deny_precedes_cache_validation(self) -> None:
        with mock.patch.dict(os.environ, {"HOME": "relative"}, clear=True):
            output = self._decision(
                {
                    "toolName": "bash",
                    "toolArgs": {"command": "python script.py"},
                }
            )

        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("uv run python", output["permissionDecisionReason"])

    def test_allow_uv_run(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.dict(os.environ, {"HOME": root}, clear=True):
                result = run_hook(
                    SCRIPT_PATH,
                    {
                        "toolName": "bash",
                        "toolArgs": {"command": "uv run python script.py"},
                    },
                )
        self.assertEqual(result.returncode, 0)
        if sys.platform == "win32":
            self.assertEqual(result.stdout.strip(), "")
        else:
            command = json.loads(result.stdout)["modifiedArgs"]["command"]
            cache = pathlib.Path(root).resolve() / (
                "Library/Caches/github-copilot/uv"
                if sys.platform == "darwin"
                else ".cache/github-copilot/uv"
            )
            self.assertEqual(
                command,
                f"export UV_CACHE_DIR={shlex.quote(str(cache))}; "
                "uv run python script.py",
            )

    def test_rewrite_preserves_other_tool_arguments(self) -> None:
        if sys.platform == "win32":
            self.skipTest("Windows does not rewrite uv cache paths")

        with tempfile.TemporaryDirectory() as root:
            with mock.patch.dict(os.environ, {"HOME": root}, clear=True):
                output = self._decision(
                    {
                        "toolName": "bash",
                        "toolArgs": {
                            "command": "uv run script.py",
                            "description": "Run script",
                        },
                    }
                )

        self.assertEqual(output["modifiedArgs"]["description"], "Run script")

    def test_allows_non_bash_tools_without_rewriting(self) -> None:
        for payload in (
            {"toolName": "edit", "toolArgs": {"path": "/tmp/foo.txt"}},
            {
                "toolName": "powershell",
                "toolArgs": {"command": "uv run script.py"},
            },
        ):
            with self.subTest(tool_name=payload["toolName"]):
                self._assert_allowed(payload)

    def test_invalid_json_denies(self) -> None:
        output = self._decision("not valid json")
        self.assertEqual(output["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
