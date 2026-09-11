import contextlib
import io
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
SCRIPT_PATH = REPO_ROOT / "home/private_dot_copilot/hooks/scripts/executable_uv-enforcer.py"


uve = load_script("uv_enforcer", SCRIPT_PATH)


# ── python / python3 blocked ─────────────────────────────────────────────


class TestPythonBlocked(unittest.TestCase):

    def test_python_bare(self) -> None:
        self.assertIsNotNone(uve.check_command("python"))

    def test_python_script(self) -> None:
        self.assertIsNotNone(uve.check_command("python script.py"))

    def test_python3_script(self) -> None:
        self.assertIsNotNone(uve.check_command("python3 script.py"))

    def test_versioned_python_script(self) -> None:
        self.assertIsNotNone(uve.check_command("python3.13 script.py"))

    def test_versioned_python_exe_script(self) -> None:
        self.assertIsNotNone(uve.check_command("python3.13.exe script.py"))

    def test_python_with_flags(self) -> None:
        self.assertIsNotNone(uve.check_command("python -m pytest"))

    def test_python_with_env_prefix(self) -> None:
        self.assertIsNotNone(uve.check_command("PYTHONPATH=/foo python script.py"))

    def test_sudo_python(self) -> None:
        self.assertIsNotNone(uve.check_command("sudo python script.py"))

    def test_sudo_E_python(self) -> None:
        self.assertIsNotNone(uve.check_command("sudo -E python3 -m pytest"))

    def test_env_python(self) -> None:
        self.assertIsNotNone(uve.check_command("env python script.py"))

    def test_absolute_path_python(self) -> None:
        self.assertIsNotNone(uve.check_command("/usr/bin/python3 script.py"))

    def test_absolute_path_pip(self) -> None:
        self.assertIsNotNone(uve.check_command("/usr/local/bin/pip install requests"))

    def test_absolute_path_env_python(self) -> None:
        """/usr/bin/env python3 must not bypass prefix detection."""
        self.assertIsNotNone(uve.check_command("/usr/bin/env python3 script.py"))

    def test_absolute_path_sudo_python(self) -> None:
        """/usr/bin/sudo python3 must not bypass prefix detection."""
        self.assertIsNotNone(uve.check_command("/usr/bin/sudo python3 script.py"))

    def test_sudo_u_python(self) -> None:
        """sudo -u root python3 must not bypass via flag argument."""
        self.assertIsNotNone(uve.check_command("sudo -u root python3 script.py"))

    def test_sudo_u_user_pip(self) -> None:
        self.assertIsNotNone(uve.check_command("sudo -u nobody pip install requests"))

    def test_env_u_python(self) -> None:
        """env -u PYTHONPATH python3 must not bypass via flag argument."""
        self.assertIsNotNone(uve.check_command("env -u PYTHONPATH python3 script.py"))

    def test_command_python(self) -> None:
        """command python must not bypass via command builtin."""
        self.assertIsNotNone(uve.check_command("command python script.py"))

    def test_command_pip(self) -> None:
        """command pip must not bypass via command builtin."""
        self.assertIsNotNone(uve.check_command("command pip install requests"))


# ── pip / pip3 blocked ────────────────────────────────────────────────────


class TestPipBlocked(unittest.TestCase):

    def test_pip_install(self) -> None:
        self.assertIsNotNone(uve.check_command("pip install requests"))

    def test_pip3_install(self) -> None:
        self.assertIsNotNone(uve.check_command("pip3 install requests"))

    def test_versioned_pip_install(self) -> None:
        self.assertIsNotNone(uve.check_command("pip3.13 install requests"))

    def test_versioned_pip_exe_install(self) -> None:
        self.assertIsNotNone(uve.check_command("pip3.13.exe install requests"))

    def test_pip_freeze(self) -> None:
        self.assertIsNotNone(uve.check_command("pip freeze"))

    def test_pip_list(self) -> None:
        self.assertIsNotNone(uve.check_command("pip list"))


# ── uv commands allowed ──────────────────────────────────────────────────


class TestUvAllowed(unittest.TestCase):

    def test_uv_run_python(self) -> None:
        self.assertIsNone(uve.check_command("uv run python script.py"))

    def test_uv_run_script(self) -> None:
        self.assertIsNone(uve.check_command("uv run script.py"))

    def test_uv_add(self) -> None:
        self.assertIsNone(uve.check_command("uv add requests"))

    def test_uv_pip_install(self) -> None:
        self.assertIsNone(uve.check_command("uv pip install requests"))

    def test_uv_bare(self) -> None:
        self.assertIsNone(uve.check_command("uv"))

    def test_uv_run_pytest(self) -> None:
        self.assertIsNone(uve.check_command("uv run -m pytest -v"))


# ── Shell chains ──────────────────────────────────────────────────────────


class TestShellChains(unittest.TestCase):

    def test_chained_python_blocked(self) -> None:
        self.assertIsNotNone(uve.check_command("echo ok && python script.py"))

    def test_chained_uv_allowed(self) -> None:
        self.assertIsNone(uve.check_command("echo ok && uv run python script.py"))

    def test_semicolon_chained_pip(self) -> None:
        self.assertIsNotNone(uve.check_command("cd /tmp; pip install foo"))

    def test_piped_python(self) -> None:
        self.assertIsNotNone(uve.check_command("echo foo | python"))

    def test_uv_leading_with_pip_later_blocked(self) -> None:
        """uv in the first segment does not suppress checks on later segments."""
        self.assertIsNotNone(uve.check_command("uv run script.py && pip install foo"))

    def test_non_uv_leading_with_pip_later(self) -> None:
        """pip in a later segment is blocked when the chain doesn't start with uv."""
        self.assertIsNotNone(uve.check_command("echo ok && pip install foo"))


# ── Non-Python commands allowed ───────────────────────────────────────────


class TestUnrelatedAllowed(unittest.TestCase):

    def test_empty_command(self) -> None:
        self.assertIsNone(uve.check_command(""))

    def test_git_status(self) -> None:
        self.assertIsNone(uve.check_command("git status"))

    def test_node(self) -> None:
        self.assertIsNone(uve.check_command("node script.js"))

    def test_npm_install(self) -> None:
        self.assertIsNone(uve.check_command("npm install"))


# ── Integration tests (stdin → stdout) ───────────────────────────────────


class TestMainIntegration(unittest.TestCase):
    """Exercise the full stdin → stdout JSON flow."""

    def _decision(self, payload: dict | str) -> dict:
        result = run_hook(SCRIPT_PATH, payload)
        self.assertEqual(result.returncode, 0)
        return json.loads(result.stdout)

    def _assert_allowed(self, payload: dict) -> None:
        result = run_hook(SCRIPT_PATH, payload)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_deny_bare_python(self) -> None:
        out = self._decision({
            "toolName": "bash",
            "toolArgs": {"command": "python script.py"},
        })
        self.assertEqual(out["permissionDecision"], "deny")

    def test_allow_uv_run(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.dict(os.environ, {"HOME": root}, clear=True):
                result = run_hook(SCRIPT_PATH, {
                    "toolName": "bash",
                    "toolArgs": {"command": "uv run python script.py"},
                })
        self.assertEqual(result.returncode, 0)
        if sys.platform == "win32":
            self.assertEqual(result.stdout.strip(), "")
        else:
            self.assertTrue(json.loads(result.stdout)["modifiedArgs"]["command"].endswith("; uv run python script.py"))

    def test_allow_non_bash_tool(self) -> None:
        self._assert_allowed({
            "toolName": "edit",
            "toolArgs": {"path": "/tmp/foo.txt"},
        })

    def test_powershell_keeps_the_original_command(self) -> None:
        self._assert_allowed({
            "toolName": "powershell",
            "toolArgs": {"command": "uv run script.py"},
        })

    def test_invalid_json_denies(self) -> None:
        out = self._decision("not valid json")
        self.assertEqual(out["permissionDecision"], "deny")


@unittest.skipIf(os.name == "nt", "POSIX cache path checks")
class TestCommandLocalCache(unittest.TestCase):
    def _main(self, command, *, platform="linux", tool="bash", env=None, serialized=False):
        args = {"command": command, "description": "keep", "initial_wait": 120}
        payload = {"toolName": tool, "toolArgs": json.dumps(args) if serialized else args}
        output = io.StringIO()
        with mock.patch.object(uve, "read_input", return_value=payload), mock.patch.object(uve.sys, "platform", platform), mock.patch.dict(os.environ, env or {}, clear=True), contextlib.redirect_stdout(output):
            try:
                uve.main()
            except SystemExit:
                pass
        return json.loads(output.getvalue()) if output.getvalue() else None

    def test_prefix_quotes_cache_and_preserves_command_and_other_args(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            home = pathlib.Path(root).resolve()
            cache_home = home / "spaces 'quotes; $dollars"
            env = {"HOME": str(home), "XDG_CACHE_HOME": str(cache_home)}
            commands = (
                "uv run script.py",
                "UV_CACHE_DIR=/explicit uv run script.py",
                "uv --cache-dir /explicit run script.py",
                "export UV_CACHE_DIR=/explicit; uv run script.py",
                "echo hello\nuv cache dir",
                "git status",
            )
            for command in commands:
                for serialized in (True, False):
                    with self.subTest(command=command, serialized=serialized):
                        output = self._main(command, env=env, serialized=serialized)
                        expected = f"export UV_CACHE_DIR={shlex.quote(str(cache_home / 'github-copilot/uv'))}; {command}"
                        self.assertEqual(output, {"modifiedArgs": {
                            "command": expected, "description": "keep", "initial_wait": 120,
                        }})
                        self.assertIsNone(self._main(expected, env=env))
            self.assertFalse(cache_home.exists(), "the hook only selects a path")

    def test_windows_powershell_and_non_shell_tools_are_unchanged(self) -> None:
        for platform, tool in (("win32", "bash"), ("win32", "powershell"), ("linux", "powershell"), ("darwin", "edit")):
            with self.subTest(platform=platform, tool=tool):
                self.assertIsNone(self._main("uv run script.py", platform=platform, tool=tool, env={"UV_CACHE_DIR": "/host-override"}))

    def test_python_and_pip_enforcement_precedes_cache_validation(self) -> None:
        for command in ("python script.py", "pip install requests", "echo ok && python3 script.py"):
            with self.subTest(command=command):
                output = self._main(command, env={"UV_CACHE_DIR": "/invalid-launch"})
                self.assertEqual(output["permissionDecision"], "deny")
                self.assertIn("Use 'uv", output["permissionDecisionReason"])
                self.assertNotIn("modifiedArgs", output)

    def test_invalid_cache_environment_denies_with_actionable_reason(self) -> None:
        output = self._main("uv cache dir", env={"UV_CACHE_DIR": ""})
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("launch-environment UV_CACHE_DIR", output["permissionDecisionReason"])

    def test_empty_command_remains_silent(self) -> None:
        self.assertIsNone(self._main(""))


if __name__ == "__main__":
    unittest.main()
