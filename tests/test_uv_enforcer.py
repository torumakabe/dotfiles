import json
import pathlib
import shutil
import subprocess
import unittest

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

    def _assert_unchanged(self, payload: dict) -> None:
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
        payload = {
            "toolName": "bash",
            "toolArgs": {"command": "uv run python script.py"},
        }
        result = run_hook(SCRIPT_PATH, payload)
        self.assertEqual(result.returncode, 0)
        modified = json.loads(result.stdout)["modifiedArgs"]
        self.assertEqual(
            modified,
            uve.with_copilot_uv_cache("bash", payload["toolArgs"]),
        )

    def test_allow_non_bash_tool(self) -> None:
        self._assert_unchanged({
            "toolName": "edit",
            "toolArgs": {"path": "/tmp/foo.txt"},
        })

    def test_invalid_json_denies(self) -> None:
        out = self._decision("not valid json")
        self.assertEqual(out["permissionDecision"], "deny")

    def test_powershell_command_uses_script_block(self) -> None:
        modified = uve.with_copilot_uv_cache(
            "powershell",
            {"command": "uv run python script.py", "description": "test"},
            r"C:\Users\O'Brien\uv",
        )
        self.assertEqual(
            modified,
            {
                "command": (
                    "$env:UV_CACHE_DIR = 'C:\\Users\\O''Brien\\uv'; & {\n"
                    "uv run python script.py\n}"
                ),
                "description": "test",
            },
        )

    def test_platform_cache_paths_are_copilot_owned(self) -> None:
        self.assertEqual(
            uve.copilot_uv_cache_dir("linux", {}, "/home/test"),
            "/home/test/.cache/github-copilot/uv",
        )
        self.assertEqual(
            uve.copilot_uv_cache_dir(
                "linux",
                {"XDG_CACHE_HOME": "/cache"},
                "/home/test",
            ),
            "/cache/github-copilot/uv",
        )
        self.assertEqual(
            uve.copilot_uv_cache_dir("darwin", {}, "/Users/test"),
            "/Users/test/Library/Caches/github-copilot/uv",
        )
        self.assertEqual(
            uve.copilot_uv_cache_dir(
                "win32",
                {"LOCALAPPDATA": r"C:\Users\test\AppData\Local"},
                r"C:\Users\test",
            ),
            r"C:\Users\test\AppData\Local\GitHubCopilot\uv",
        )

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    def test_bash_modified_command_sets_cache_and_preserves_exit(self) -> None:
        modified = uve.with_copilot_uv_cache(
            "bash",
            {"command": 'printf "%s" "$UV_CACHE_DIR"; exit 7'},
            "/tmp/copilot uv",
        )
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", modified["command"]],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout, "/tmp/copilot uv")
        self.assertEqual(result.returncode, 7)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_modified_command_sets_cache_and_preserves_exit(self) -> None:
        modified = uve.with_copilot_uv_cache(
            "powershell",
            {"command": "Write-Output $env:UV_CACHE_DIR; exit 7"},
            r"C:\Users\O'Brien\uv",
        )
        result = subprocess.run(
            ["pwsh", "-NoLogo", "-NoProfile", "-Command", modified["command"]],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), r"C:\Users\O'Brien\uv")
        self.assertEqual(result.returncode, 7)


if __name__ == "__main__":
    unittest.main()
