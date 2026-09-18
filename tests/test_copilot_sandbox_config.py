"""Guard static Copilot sandbox configuration contracts."""

import json
import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "home"
USER_POLICY_PATH = SOURCE_ROOT / ".chezmoitemplates/copilot-user-settings.json"
POSIX_SCRIPT_PATH = SOURCE_ROOT / "run_after_35-configure-copilot-sandbox.sh.tmpl"
POWERSHELL_SCRIPT_PATH = (
    SOURCE_ROOT / "run_onchange_after_35-configure-copilot-sandbox.ps1.tmpl"
)
ZSHRC_PATH = SOURCE_ROOT / "dot_zshrc.tmpl"
POWERSHELL_PROFILE_PATH = SOURCE_ROOT / "PowerShell_profile.ps1.tmpl"

EXPECTED_MARKETPLACE = {
    "source": {"source": "github", "repo": "torumakabe/copilot-agent-plugins"},
    "autoUpdate": True,
}
EXPECTED_PLUGINS = {
    "personal-skills@torumakabe-agent-plugins": True,
    "skill-creator@torumakabe-agent-plugins": True,
}


class CopilotSandboxPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.posix = POSIX_SCRIPT_PATH.read_text(encoding="utf-8")
        cls.powershell = POWERSHELL_SCRIPT_PATH.read_text(encoding="utf-8")

    def test_platform_scripts_share_policy_version(self) -> None:
        version_pattern = r"(?m)^# Copilot sandbox policy version: (\d+)$"
        posix_version = re.findall(version_pattern, self.posix)
        powershell_version = re.findall(version_pattern, self.powershell)
        self.assertEqual(len(posix_version), 1)
        self.assertEqual(posix_version, powershell_version)

    def test_platform_scripts_describe_the_full_settings_update(self) -> None:
        expected_message = "Configured GitHub Copilot user settings in "
        obsolete_message = "Configured Copilot CLI local sandbox in "
        for script in (self.posix, self.powershell):
            self.assertIn(expected_message, script)
            self.assertNotIn(obsolete_message, script)

    def test_user_policy_has_cross_platform_defaults_and_guardrail_aliases(self) -> None:
        policy = json.loads(USER_POLICY_PATH.read_text(encoding="utf-8"))
        self.assertTrue(policy["experimental"])
        self.assertEqual(
            policy["extraKnownMarketplaces"]["torumakabe-agent-plugins"],
            EXPECTED_MARKETPLACE,
        )
        self.assertEqual(policy["enabledPlugins"], EXPECTED_PLUGINS)
        sandbox = policy["sandbox"]
        for name in (
            "enabled",
            "allowBypass",
            "addCurrentWorkingDirectory",
            "allowDevToolAccess",
        ):
            self.assertTrue(sandbox[name])
        self.assertFalse(sandbox["sandboxMcpServers"])
        self.assertFalse(sandbox["sandboxLspServers"])
        self.assertEqual(sandbox["auth"], {"git": True, "gh": True})
        self.assertEqual(
            sandbox["userPolicy"]["network"],
            {"allowOutbound": True, "allowLocalNetwork": True},
        )
        self.assertIn("--allow-all", ZSHRC_PATH.read_text(encoding="utf-8"))
        self.assertIn(
            "--allow-all",
            POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8"),
        )

    def test_platform_scripts_declare_atomic_replacement(self) -> None:
        for declaration in (
            'settings_tmp="${settings_dir}/.settings.json.$$"',
            "set -o noclobber",
            'chmod 0600 "${settings_tmp}"',
            'mv -f "${settings_tmp}" "${settings_path}"',
        ):
            self.assertIn(declaration, self.posix)
        self.assertIn("[System.IO.File]::Replace", self.powershell)
        self.assertRegex(
            self.powershell,
            r"\[System\.IO\.File\]::Move\(\$temporaryPath, \$settingsPath"
            r"(?:, \$true)?\)",
        )

    def test_posix_template_declares_environment_and_existing_enabled_defaults(
        self,
    ) -> None:
        self.assertIn(
            "sandbox_default_enabled={{ if or .codespaces .devcontainer }}"
            "false{{ else }}true{{ end }}",
            self.posix,
        )
        self.assertIn(
            'existing_enabled="${sandbox_default_enabled}"',
            self.posix,
        )

    def test_validation_precedes_writes_in_both_scripts(self) -> None:
        posix_write = self.posix.index('mkdir -p "${uv_cache_dir}"')
        self.assertLess(self.posix.index("non-boolean sandbox.enabled"), posix_write)
        self.assertLess(
            self.posix.index("non-array sandbox.userPolicy.filesystem"),
            posix_write,
        )

        powershell_write = self.powershell.index(
            "New-Item -ItemType Directory -Path $uvCacheDir"
        )
        self.assertLess(
            self.powershell.index("non-boolean sandbox.enabled"),
            powershell_write,
        )
        self.assertLess(
            self.powershell.index("non-array sandbox.userPolicy.filesystem"),
            powershell_write,
        )

    def test_absent_or_null_path_arrays_are_normalized(self) -> None:
        for path_name in ("readwritePaths", "readonlyPaths", "deniedPaths"):
            self.assertIn(f".{path_name} // []", self.posix)
            self.assertRegex(self.posix, rf"\.{path_name}\s*=")
            self.assertRegex(
                self.powershell,
                rf"Get-JsonArrayOrEmpty \(Get-JsonProperty "
                rf"-Object \$existingFilesystem -Name '{path_name}'\)",
            )

    def test_stale_policy_and_network_keys_are_removed(self) -> None:
        self.assertRegex(
            self.posix,
            r"(?s)del\(\.version\).*?del\(\.allowedHosts, \.blockedHosts\)",
        )
        self.assertIn(
            "Remove-JsonProperty -Object $userPolicy -Name 'version'",
            self.powershell,
        )
        for key in ("allowedHosts", "blockedHosts"):
            self.assertIn(
                f"Remove-JsonProperty -Object $network -Name '{key}'",
                self.powershell,
            )

    def test_unsafe_cache_configuration_is_rejected_before_creation(self) -> None:
        posix_cache_creation = self.posix.index('mkdir -p "${uv_cache_dir}"')
        powershell_cache_creation = self.powershell.index(
            "New-Item -ItemType Directory -Path $uvCacheDir"
        )
        self.assertLess(
            self.posix.index("unset launch-environment UV_CACHE_DIR"),
            posix_cache_creation,
        )
        self.assertLess(
            self.powershell.index("Unset launch-environment UV_CACHE_DIR"),
            powershell_cache_creation,
        )
        for script in (self.posix, self.powershell):
            self.assertIn("conflicts with", script)
        self.assertIn("cache path must not contain symlinks", self.posix)
        self.assertIn("refusing a settings.json symlink", self.posix)
        self.assertIn(
            "must not contain symlinks or reparse points",
            self.powershell,
        )


if __name__ == "__main__":
    unittest.main()
