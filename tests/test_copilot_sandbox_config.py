"""Verify the cross-platform Copilot CLI sandbox settings contract.

On POSIX, `sandbox.enabled` defaults to false in Codespaces and this
repository's Dev Container, and to true elsewhere. `/sandbox disable`
persists `sandbox.enabled=false` in `~/.copilot/settings.json`, and that value
must survive every future `chezmoi apply` until `/sandbox enable` restores it. The
``CopilotSandboxEnabledPreservationTests`` below execute the rendered POSIX
and PowerShell scripts against seeded settings files to pin that contract.
"""

import json
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "home"
USER_POLICY_PATH = SOURCE_ROOT / ".chezmoitemplates/copilot-user-settings.json"
POSIX_SCRIPT_PATH = SOURCE_ROOT / "run_onchange_after_35-configure-copilot-sandbox.sh.tmpl"
POWERSHELL_SCRIPT_PATH = (
    SOURCE_ROOT / "run_onchange_after_35-configure-copilot-sandbox.ps1.tmpl"
)
ZSHRC_PATH = SOURCE_ROOT / "dot_zshrc.tmpl"
POWERSHELL_PROFILE_PATH = SOURCE_ROOT / "PowerShell_profile.ps1.tmpl"

FILESYSTEM_PATHS = {
    "readwritePaths": ["/tmp/readwrite"],
    "readonlyPaths": ["/tmp/readonly"],
    "deniedPaths": ["/tmp/denied"],
}

# Sentinel distinguishing "no sandbox.enabled key seeded" from any JSON value,
# including `None` (JSON null), which is itself one of the invalid cases.
_ENABLED_KEY_ABSENT = object()


def _render(
    path: pathlib.Path,
    platform: str,
    *,
    codespaces: bool = False,
    devcontainer: bool = False,
) -> str:
    result = subprocess.run(
        [
            "chezmoi",
            "--source",
            str(SOURCE_ROOT),
            "execute-template",
            "--override-data",
            json.dumps(
                {
                    "chezmoi": {"os": platform, "arch": "amd64"},
                    "codespaces": codespaces,
                    "devcontainer": devcontainer,
                }
            ),
            "--file",
            str(path),
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return result.stdout


def _seed_settings(home: pathlib.Path, enabled: object = _ENABLED_KEY_ABSENT) -> pathlib.Path:
    settings_path = home / ".copilot/settings.json"
    settings_path.parent.mkdir(parents=True)
    sandbox: dict = {
        "userPolicy": {
            "version": 1,
            "filesystem": FILESYSTEM_PATHS,
            "network": {
                "allowedHosts": ["api.github.com"],
                "blockedHosts": ["example.invalid"],
            },
        }
    }
    if enabled is not _ENABLED_KEY_ABSENT:
        sandbox["enabled"] = enabled
    settings_path.write_text(
        json.dumps({"unrelated": {"keep": True}, "sandbox": sandbox}),
        encoding="utf-8",
    )
    return settings_path


def _run_posix_script(
    home: pathlib.Path,
    settings_path: pathlib.Path,
    *,
    codespaces: bool = False,
    devcontainer: bool = False,
) -> subprocess.CompletedProcess[str]:
    script_path = home / "configure-sandbox.sh"
    script_path.write_text(
        _render(
            POSIX_SCRIPT_PATH,
            "linux",
            codespaces=codespaces,
            devcontainer=devcontainer,
        ),
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(script_path)],
        env={
            **os.environ,
            "COPILOT_HOME": str(settings_path.parent),
            "HOME": str(home),
        },
        check=False,
        capture_output=True,
        encoding="utf-8",
    )


def _run_powershell_script(
    home: pathlib.Path, settings_path: pathlib.Path
) -> subprocess.CompletedProcess[str]:
    script_path = home / "configure-sandbox.ps1"
    script_path.write_text(_render(POWERSHELL_SCRIPT_PATH, "windows"), encoding="utf-8")
    return subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-File", str(script_path)],
        env={**os.environ, "COPILOT_HOME": str(settings_path.parent)},
        check=False,
        capture_output=True,
        encoding="utf-8",
    )


class CopilotSandboxPolicyTests(unittest.TestCase):
    def test_user_policy_has_the_cross_platform_defaults(self) -> None:
        policy = json.loads(USER_POLICY_PATH.read_text(encoding="utf-8"))

        self.assertTrue(policy["experimental"])
        sandbox = policy["sandbox"]
        self.assertTrue(sandbox["enabled"])
        self.assertTrue(sandbox["allowBypass"])
        self.assertFalse(sandbox["sandboxMcpServers"])
        self.assertFalse(sandbox["sandboxLspServers"])
        self.assertTrue(sandbox["addCurrentWorkingDirectory"])
        self.assertTrue(sandbox["allowDevToolAccess"])
        self.assertEqual(sandbox["auth"], {"git": True, "gh": True})
        self.assertEqual(
            sandbox["userPolicy"]["network"],
            {"allowOutbound": True, "allowLocalNetwork": True},
        )

    def test_guardrails_aliases_keep_allow_all(self) -> None:
        self.assertIn("--allow-all", ZSHRC_PATH.read_text(encoding="utf-8"))
        self.assertIn("--allow-all", POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8"))

    def test_posix_merge_uses_a_private_temporary_directory(self) -> None:
        script = POSIX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn('tmp_dir="$(mktemp -d)"', script)
        self.assertIn('settings_tmp="$(mktemp "${settings_dir}/.settings.json.XXXXXX")"', script)
        self.assertIn('chmod 0600 "${settings_tmp}"', script)

    def test_powershell_merge_replaces_settings_atomically(self) -> None:
        script = POWERSHELL_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("[System.IO.File]::Replace", script)
        self.assertIn(
            "[System.IO.File]::Move($temporaryPath, $settingsPath, $true)",
            script,
        )


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class CopilotSandboxMergeTests(unittest.TestCase):
    def _assert_settings(self, settings: dict, expected_enabled: bool = True) -> None:
        self.assertEqual(settings["unrelated"], {"keep": True})
        self.assertTrue(settings["experimental"])

        sandbox = settings["sandbox"]
        self.assertIs(sandbox["enabled"], expected_enabled)
        self.assertTrue(sandbox["allowBypass"])
        self.assertFalse(sandbox["sandboxMcpServers"])
        self.assertFalse(sandbox["sandboxLspServers"])
        self.assertTrue(sandbox["addCurrentWorkingDirectory"])
        self.assertTrue(sandbox["allowDevToolAccess"])
        self.assertEqual(sandbox["auth"], {"git": True, "gh": True})

        policy = sandbox["userPolicy"]
        self.assertNotIn("version", policy)
        self.assertEqual(
            {name: policy["filesystem"][name] for name in FILESYSTEM_PATHS},
            FILESYSTEM_PATHS,
        )
        self.assertFalse(policy["filesystem"]["clearPolicyOnExit"])
        self.assertEqual(
            policy["network"],
            {"allowOutbound": True, "allowLocalNetwork": True},
        )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_merge_preserves_paths_and_removes_stale_network_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)
            result = _run_posix_script(home, settings_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_settings(json.loads(settings_path.read_text(encoding="utf-8")))

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_merge_preserves_paths_and_removes_stale_network_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)
            result = _run_powershell_script(home, settings_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_settings(
                json.loads(settings_path.read_text(encoding="utf-8-sig"))
            )


# (case name, seeded value, expected merged value). ``_ENABLED_KEY_ABSENT``
# seeds an existing settings file without a `sandbox.enabled` key.
VALID_ENABLED_CASES = (
    ("missing", _ENABLED_KEY_ABSENT, True),
    ("true", True, True),
    ("false", False, False),
)

# (case name, seeded value). Each must make the script fail loudly instead of
# silently coercing the value to a boolean.
INVALID_ENABLED_CASES = (
    ("null", None),
    ("string", "disabled"),
    ("number", 1),
    ("array", [True]),
)

# (case name, Codespaces, Dev Container, first-apply default)
POSIX_ENVIRONMENT_CASES = (
    ("ordinary-linux", False, False, True),
    ("codespaces", True, False, False),
    ("devcontainer", False, True, False),
)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class CopilotSandboxEnabledPreservationTests(unittest.TestCase):
    """Pin the environment defaults and user override contract in ADR-026."""

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_defaults_enabled_when_settings_file_is_absent(self) -> None:
        for environment, codespaces, devcontainer, expected in POSIX_ENVIRONMENT_CASES:
            with self.subTest(environment=environment):
                with tempfile.TemporaryDirectory() as temp_dir:
                    home = pathlib.Path(temp_dir)
                    settings_path = home / ".copilot/settings.json"
                    result = _run_posix_script(
                        home,
                        settings_path,
                        codespaces=codespaces,
                        devcontainer=devcontainer,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    settings = json.loads(settings_path.read_text(encoding="utf-8"))
                    self.assertIs(settings["sandbox"]["enabled"], expected)
                    self.assertEqual(
                        stat.S_IMODE(settings_path.stat().st_mode),
                        0o600,
                    )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_preserves_or_defaults_enabled(self) -> None:
        for environment, codespaces, devcontainer, default in POSIX_ENVIRONMENT_CASES:
            for case_name, seeded, ordinary_expected in VALID_ENABLED_CASES:
                expected = default if seeded is _ENABLED_KEY_ABSENT else ordinary_expected
                with self.subTest(environment=environment, case=case_name):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        home = pathlib.Path(temp_dir)
                        settings_path = _seed_settings(home, enabled=seeded)
                        result = _run_posix_script(
                            home,
                            settings_path,
                            codespaces=codespaces,
                            devcontainer=devcontainer,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        settings = json.loads(settings_path.read_text(encoding="utf-8"))
                        self.assertIs(settings["sandbox"]["enabled"], expected)
                        self.assertEqual(
                            stat.S_IMODE(settings_path.stat().st_mode),
                            0o600,
                        )

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_preserves_or_defaults_enabled(self) -> None:
        for case_name, seeded, expected in VALID_ENABLED_CASES:
            with self.subTest(case=case_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    home = pathlib.Path(temp_dir)
                    settings_path = _seed_settings(home, enabled=seeded)
                    result = _run_powershell_script(home, settings_path)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    settings = json.loads(
                        settings_path.read_text(encoding="utf-8-sig")
                    )
                    self.assertIs(settings["sandbox"]["enabled"], expected)

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_rejects_non_boolean_enabled(self) -> None:
        for environment, codespaces, devcontainer, _ in POSIX_ENVIRONMENT_CASES:
            for case_name, seeded in INVALID_ENABLED_CASES:
                with self.subTest(environment=environment, case=case_name):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        home = pathlib.Path(temp_dir)
                        settings_path = _seed_settings(home, enabled=seeded)
                        original = settings_path.read_text(encoding="utf-8")
                        result = _run_posix_script(
                            home,
                            settings_path,
                            codespaces=codespaces,
                            devcontainer=devcontainer,
                        )
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("non-boolean", result.stderr)
                        self.assertIn("sandbox.enabled", result.stderr)
                        self.assertEqual(
                            settings_path.read_text(encoding="utf-8"), original
                        )

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_rejects_non_boolean_enabled(self) -> None:
        for case_name, seeded in INVALID_ENABLED_CASES:
            with self.subTest(case=case_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    home = pathlib.Path(temp_dir)
                    settings_path = _seed_settings(home, enabled=seeded)
                    original = settings_path.read_text(encoding="utf-8")
                    result = _run_powershell_script(home, settings_path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("non-boolean", result.stderr)
                    self.assertIn("sandbox.enabled", result.stderr)
                    self.assertEqual(
                        settings_path.read_text(encoding="utf-8"), original
                    )


if __name__ == "__main__":
    unittest.main()
