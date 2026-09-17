import json
import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests._helpers import load_script, run_hook, scoped_environ


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
        with scoped_environ({"HOME": "relative"}):
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
            if sys.platform == "win32":
                local_app_data = pathlib.Path(root) / "local-app-data"
                local_app_data.mkdir()
                env = {
                    "LOCALAPPDATA": str(local_app_data),
                    "USERPROFILE": root,
                }
                payload = {
                    "toolName": "powershell",
                    "toolArgs": {"command": "uv run python script.py"},
                }
            else:
                env = {"HOME": root}
                payload = {
                    "toolName": "bash",
                    "toolArgs": {"command": "uv run python script.py"},
                }
            with scoped_environ(
                env,
                unset=("UV_CACHE_DIR", "XDG_CACHE_HOME"),
            ):
                result = run_hook(SCRIPT_PATH, payload)
        self.assertEqual(result.returncode, 0)
        if sys.platform == "win32":
            command = json.loads(result.stdout)["modifiedArgs"]["command"]
            cache = pathlib.Path(root).resolve() / "local-app-data/github-copilot/uv"
            self.assertEqual(
                command,
                f"$env:UV_CACHE_DIR = '{cache}'; uv run python script.py",
            )
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
        with tempfile.TemporaryDirectory() as root:
            if sys.platform == "win32":
                local_app_data = pathlib.Path(root) / "local-app-data"
                local_app_data.mkdir()
                env = {
                    "LOCALAPPDATA": str(local_app_data),
                    "USERPROFILE": root,
                }
                tool_name = "powershell"
            else:
                env = {"HOME": root}
                tool_name = "bash"
            with scoped_environ(
                env,
                unset=("UV_CACHE_DIR", "XDG_CACHE_HOME"),
            ):
                output = self._decision(
                    {
                        "toolName": tool_name,
                        "toolArgs": {
                            "command": "uv run script.py",
                            "description": "Run script",
                        },
                    }
                )

        self.assertEqual(output["modifiedArgs"]["description"], "Run script")

    def test_allows_non_bash_tools_without_rewriting(self) -> None:
        platform_payload = (
            {
                "toolName": "bash",
                "toolArgs": {"command": "uv run script.py"},
            }
            if sys.platform == "win32"
            else {
                "toolName": "powershell",
                "toolArgs": {"command": "uv run script.py"},
            }
        )
        for payload in (
            {"toolName": "edit", "toolArgs": {"path": "/tmp/foo.txt"}},
            platform_payload,
        ):
            with self.subTest(tool_name=payload["toolName"]):
                self._assert_allowed(payload)

    def test_invalid_json_denies(self) -> None:
        output = self._decision("not valid json")
        self.assertEqual(output["permissionDecision"], "deny")


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class WindowsCachePathTests(unittest.TestCase):
    def _create_junction(self, path: pathlib.Path, target: pathlib.Path) -> None:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(path), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.fail(result.stderr or result.stdout or "failed to create junction")

    def test_windows_cache_path_uses_local_app_data(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            local_app_data = pathlib.Path(root) / "local-app-data"
            local_app_data.mkdir()
            with scoped_environ(
                {
                    "LOCALAPPDATA": str(local_app_data),
                    "USERPROFILE": root,
                },
                unset=("UV_CACHE_DIR",),
            ), mock.patch.object(uve.sys, "platform", "win32"):
                self.assertEqual(
                    uve.copilot_uv_cache_dir_windows(),
                    str(local_app_data.resolve() / "github-copilot" / "uv"),
                )

    def test_windows_cache_path_rejects_unsafe_environment(self) -> None:
        cases = (
            {"LOCALAPPDATA": "relative"},
            {"LOCALAPPDATA": r"C:\temp\..\cache"},
            {"LOCALAPPDATA": r"\\server\share\cache"},
            {"LOCALAPPDATA": r"C:\\"},
            {
                "LOCALAPPDATA": r"C:\Users\TestUser\AppData\Local",
                "UV_CACHE_DIR": r"C:\explicit-cache",
            },
        )
        for env in cases:
            with self.subTest(env=env):
                unset = () if "UV_CACHE_DIR" in env else ("UV_CACHE_DIR",)
                with scoped_environ(
                    {**env, "USERPROFILE": r"C:\Users\TestUser"},
                    unset=unset,
                ), mock.patch.object(uve.sys, "platform", "win32"):
                    with self.assertRaises((ValueError, OSError)):
                        uve.copilot_uv_cache_dir_windows()

    def test_windows_cache_path_rejects_junction(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = pathlib.Path(root)
            home = root_path / "home"
            target = home / "redirect-target"
            target.mkdir(parents=True)
            app_data = home / "AppData"
            app_data.mkdir(parents=True)
            local_app_data = app_data / "Local"
            self._create_junction(local_app_data, target)
            with scoped_environ(
                {
                    "LOCALAPPDATA": str(local_app_data),
                    "USERPROFILE": str(home),
                },
                unset=("UV_CACHE_DIR",),
            ), mock.patch.object(uve.sys, "platform", "win32"):
                with self.assertRaises((ValueError, OSError)):
                    uve.copilot_uv_cache_dir_windows()


if __name__ == "__main__":
    unittest.main()
