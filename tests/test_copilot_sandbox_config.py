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
REMOVE_PATH = SOURCE_ROOT / ".chezmoiremove"
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
UNKNOWN_SETTINGS = {
    "extraKnownMarketplaces": {
        "existing-marketplace": {
            "source": {
                "source": "github",
                "repo": "example/existing-marketplace",
            }
        }
    },
    "enabledPlugins": {"existing-plugin@existing-marketplace": False},
    "sandbox": {"keep": "sandbox"},
    "userPolicy": {"keep": "policy"},
    "filesystem": {"keep": {"nested": "filesystem"}},
    "network": {"keep": ["network"]},
}
EXPECTED_MARKETPLACE = {
    "source": {
        "source": "github",
        "repo": "torumakabe/copilot-agent-plugins",
    },
    "autoUpdate": True,
}
EXPECTED_PLUGINS = {
    "personal-skills@torumakabe-agent-plugins": True,
    "skill-creator@torumakabe-agent-plugins": True,
}


def _nested_unknown(depth: int) -> object:
    value: object = "deep-value"
    for level in reversed(range(depth)):
        value = {f"level{level}": value}
    return value


DEEP_UNKNOWN = _nested_unknown(25)

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
        "keep": UNKNOWN_SETTINGS["sandbox"]["keep"],
        "userPolicy": {
            "version": 1,
            "keep": UNKNOWN_SETTINGS["userPolicy"]["keep"],
            "filesystem": {
                **FILESYSTEM_PATHS,
                **UNKNOWN_SETTINGS["filesystem"],
            },
            "network": {
                "allowedHosts": ["api.github.com"],
                "blockedHosts": ["example.invalid"],
                **UNKNOWN_SETTINGS["network"],
            },
        }
    }
    if enabled is not _ENABLED_KEY_ABSENT:
        sandbox["enabled"] = enabled
    settings_path.write_text(
        json.dumps(
            {
                "unrelated": {"keep": True},
                "deepUnknown": DEEP_UNKNOWN,
                "extraKnownMarketplaces": UNKNOWN_SETTINGS[
                    "extraKnownMarketplaces"
                ],
                "enabledPlugins": UNKNOWN_SETTINGS["enabledPlugins"],
                "sandbox": sandbox,
            }
        ),
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
        env={
            **os.environ,
            "COPILOT_HOME": str(settings_path.parent),
            "HOME": str(home),
            "USERPROFILE": str(home),
        },
        check=False,
        capture_output=True,
        encoding="utf-8",
    )


class CopilotSandboxPolicyTests(unittest.TestCase):
    def test_platform_scripts_share_policy_version(self) -> None:
        marker = "# Copilot sandbox policy version: "
        versions = []

        for script_path in (POSIX_SCRIPT_PATH, POWERSHELL_SCRIPT_PATH):
            matches = [
                line.removeprefix(marker)
                for line in script_path.read_text(encoding="utf-8").splitlines()
                if line.startswith(marker)
            ]
            self.assertEqual(len(matches), 1, script_path)
            versions.append(matches[0])

        self.assertEqual(versions[0], versions[1])

    def test_user_policy_has_the_cross_platform_defaults(self) -> None:
        policy = json.loads(USER_POLICY_PATH.read_text(encoding="utf-8"))

        self.assertTrue(policy["experimental"])
        self.assertEqual(
            policy["extraKnownMarketplaces"]["torumakabe-agent-plugins"],
            EXPECTED_MARKETPLACE,
        )
        self.assertEqual(policy["enabledPlugins"], EXPECTED_PLUGINS)
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

    def test_plugin_skills_replace_legacy_user_copies(self) -> None:
        skill_names = ("agentfinder", "japanese-technical-writing", "lsp-setup")
        removals = {
            line
            for line in REMOVE_PATH.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        }

        for skill_name in skill_names:
            self.assertIn(f".copilot/skills/{skill_name}", removals)
            self.assertFalse(
                any(
                    path.is_file()
                    for path in (
                        SOURCE_ROOT / "private_dot_copilot" / "skills" / skill_name
                    ).rglob("*")
                )
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
    def _assert_settings(
        self, settings: dict, home: pathlib.Path, expected_enabled: bool = True
    ) -> None:
        self.assertEqual(settings["unrelated"], {"keep": True})
        self.assertEqual(settings["deepUnknown"], DEEP_UNKNOWN)
        self.assertTrue(settings["experimental"])
        self.assertEqual(
            settings["extraKnownMarketplaces"],
            {
                **UNKNOWN_SETTINGS["extraKnownMarketplaces"],
                "torumakabe-agent-plugins": EXPECTED_MARKETPLACE,
            },
        )
        self.assertEqual(
            settings["enabledPlugins"],
            {
                **UNKNOWN_SETTINGS["enabledPlugins"],
                **EXPECTED_PLUGINS,
            },
        )

        sandbox = settings["sandbox"]
        self.assertEqual(sandbox["keep"], UNKNOWN_SETTINGS["sandbox"]["keep"])
        self.assertIs(sandbox["enabled"], expected_enabled)
        self.assertTrue(sandbox["allowBypass"])
        self.assertFalse(sandbox["sandboxMcpServers"])
        self.assertFalse(sandbox["sandboxLspServers"])
        self.assertTrue(sandbox["addCurrentWorkingDirectory"])
        self.assertTrue(sandbox["allowDevToolAccess"])
        self.assertEqual(sandbox["auth"], {"git": True, "gh": True})

        policy = sandbox["userPolicy"]
        self.assertEqual(policy["keep"], UNKNOWN_SETTINGS["userPolicy"]["keep"])
        self.assertNotIn("version", policy)
        expected_paths = {
            **FILESYSTEM_PATHS,
            "readonlyPaths": [
                *FILESYSTEM_PATHS["readonlyPaths"],
                str(home / ".config/mise/config.toml"),
            ],
        }
        self.assertEqual(
            {name: policy["filesystem"][name] for name in FILESYSTEM_PATHS},
            expected_paths,
        )
        self.assertEqual(
            policy["filesystem"]["keep"],
            UNKNOWN_SETTINGS["filesystem"]["keep"],
        )
        self.assertFalse(policy["filesystem"]["clearPolicyOnExit"])
        self.assertTrue(policy["network"]["allowOutbound"])
        self.assertTrue(policy["network"]["allowLocalNetwork"])
        self.assertEqual(
            policy["network"]["keep"],
            UNKNOWN_SETTINGS["network"]["keep"],
        )
        self.assertNotIn("allowedHosts", policy["network"])
        self.assertNotIn("blockedHosts", policy["network"])

    def _assert_normalizes_empty_filesystem_paths(self, run_script) -> None:
        for path_name in FILESYSTEM_PATHS:
            for case_name, remove_key in (("missing", True), ("null", False)):
                with self.subTest(path=path_name, case=case_name):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        home = pathlib.Path(temp_dir)
                        settings_path = _seed_settings(home)
                        settings = json.loads(settings_path.read_text(encoding="utf-8"))
                        filesystem = settings["sandbox"]["userPolicy"]["filesystem"]
                        if remove_key:
                            filesystem.pop(path_name)
                        else:
                            filesystem[path_name] = None
                        settings_path.write_text(json.dumps(settings), encoding="utf-8")

                        result = run_script(home, settings_path)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        merged = json.loads(
                            settings_path.read_text(encoding="utf-8-sig")
                        )
                        self.assertEqual(
                            merged["sandbox"]["userPolicy"]["filesystem"][path_name],
                            (
                                [str(home / ".config/mise/config.toml")]
                                if path_name == "readonlyPaths"
                                else []
                            ),
                        )

    def _assert_mise_config_path_is_idempotent(self, run_script) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)

            first = run_script(home, settings_path)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = run_script(home, settings_path)
            self.assertEqual(second.returncode, 0, second.stderr)

            settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
            readonly_paths = settings["sandbox"]["userPolicy"]["filesystem"][
                "readonlyPaths"
            ]
            self.assertEqual(
                readonly_paths,
                [
                    *FILESYSTEM_PATHS["readonlyPaths"],
                    str(home / ".config/mise/config.toml"),
                ],
            )

    def _assert_preserves_existing_mise_config_path_position(self, run_script) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            mise_config_path = str(home / ".config/mise/config.toml")
            settings["sandbox"]["userPolicy"]["filesystem"]["readonlyPaths"] = [
                mise_config_path,
                *FILESYSTEM_PATHS["readonlyPaths"],
            ]
            settings_path.write_text(json.dumps(settings), encoding="utf-8")

            result = run_script(home, settings_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            merged = json.loads(settings_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(
                merged["sandbox"]["userPolicy"]["filesystem"]["readonlyPaths"],
                [mise_config_path, *FILESYSTEM_PATHS["readonlyPaths"]],
            )

    def _assert_rejects_invalid_filesystem_paths(self, run_script) -> None:
        invalid_cases = (
            ("string", "/tmp/not-an-array"),
            ("number", 1),
            ("boolean", True),
            ("object", {"path": "/tmp"}),
        )
        for path_name in FILESYSTEM_PATHS:
            for case_name, invalid_value in invalid_cases:
                with self.subTest(path=path_name, case=case_name):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        home = pathlib.Path(temp_dir)
                        settings_path = _seed_settings(home)
                        settings = json.loads(settings_path.read_text(encoding="utf-8"))
                        settings["sandbox"]["userPolicy"]["filesystem"][path_name] = (
                            invalid_value
                        )
                        settings_path.write_text(json.dumps(settings), encoding="utf-8")
                        original = settings_path.read_text(encoding="utf-8")

                        result = run_script(home, settings_path)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("non-array", result.stderr)
                        self.assertIn(
                            f"sandbox.userPolicy.filesystem.{path_name}",
                            result.stderr,
                        )
                        self.assertEqual(
                            settings_path.read_text(encoding="utf-8"),
                            original,
                        )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_merge_preserves_paths_and_removes_stale_network_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)
            result = _run_posix_script(home, settings_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_settings(
                json.loads(settings_path.read_text(encoding="utf-8")), home
            )

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_merge_preserves_paths_and_removes_stale_network_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)
            result = _run_powershell_script(home, settings_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_settings(
                json.loads(settings_path.read_text(encoding="utf-8-sig")), home
            )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_mise_config_path_is_idempotent(self) -> None:
        self._assert_mise_config_path_is_idempotent(_run_posix_script)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_mise_config_path_is_idempotent(self) -> None:
        self._assert_mise_config_path_is_idempotent(_run_powershell_script)

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_preserves_existing_mise_config_path_position(self) -> None:
        self._assert_preserves_existing_mise_config_path_position(_run_posix_script)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_preserves_existing_mise_config_path_position(self) -> None:
        self._assert_preserves_existing_mise_config_path_position(
            _run_powershell_script
        )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_normalizes_missing_or_null_filesystem_paths(self) -> None:
        self._assert_normalizes_empty_filesystem_paths(_run_posix_script)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_normalizes_missing_or_null_filesystem_paths(self) -> None:
        self._assert_normalizes_empty_filesystem_paths(_run_powershell_script)

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_rejects_non_array_filesystem_paths(self) -> None:
        self._assert_rejects_invalid_filesystem_paths(_run_posix_script)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_rejects_non_array_filesystem_paths(self) -> None:
        self._assert_rejects_invalid_filesystem_paths(_run_powershell_script)


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
                        settings["sandbox"]["userPolicy"]["filesystem"][
                            "readonlyPaths"
                        ],
                        [str(home / ".config/mise/config.toml")],
                    )
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
                    self.assertEqual(
                        settings["sandbox"]["userPolicy"]["filesystem"][
                            "readonlyPaths"
                        ],
                        [str(home / ".config/mise/config.toml")],
                    )

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
