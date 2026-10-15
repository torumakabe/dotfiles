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
POSIX_PROFILE_PATH = SOURCE_ROOT / "dot_profile.tmpl"
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

    def test_user_policy_has_cross_platform_defaults_and_masked_credentials(self) -> None:
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
        self.assertTrue(sandbox["sandboxMcpServers"])
        self.assertFalse(sandbox["sandboxLspServers"])
        self.assertEqual(sandbox["auth"], {"git": True, "gh": True})
        self.assertEqual(
            sandbox["userPolicy"]["network"],
            {"allowOutbound": True, "allowLocalNetwork": True},
        )
        self.assertEqual(
            sandbox["credentials"]["envVars"],
            {
                name: {"injectHosts": ["mask-only.invalid"]}
                for name in (
                    "AZURE_CLIENT_SECRET",
                    "ARM_CLIENT_SECRET",
                    "ARM_ACCESS_KEY",
                    "AZURE_STORAGE_CONNECTION_STRING",
                )
            },
        )

    def test_azure_skills_telemetry_is_disabled_in_all_shell_environments(
        self,
    ) -> None:
        self.assertIn(
            "export AZURE_MCP_COLLECT_TELEMETRY=false",
            POSIX_PROFILE_PATH.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "$env:AZURE_MCP_COLLECT_TELEMETRY = 'false'",
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
        posix_write = self.posix.index('mkdir -p "${settings_dir}"')
        self.assertLess(self.posix.index("non-boolean sandbox.enabled"), posix_write)
        self.assertLess(
            self.posix.index("non-array sandbox.userPolicy.filesystem"),
            posix_write,
        )

        powershell_write = self.powershell.index(
            "New-Item -ItemType Directory -Path $settingsDir"
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

    def test_powershell_path_arrays_are_not_wrapped_as_nested_arrays(self) -> None:
        self.assertNotIn("return ,@()", self.powershell)
        self.assertNotIn("return ,@($Value)", self.powershell)
        self.assertIn(
            "$readwritePaths = @(",
            self.powershell,
        )
        self.assertIn(
            "$readonlyPaths = @(",
            self.powershell,
        )
        self.assertIn(
            "Set-JsonProperty -Object $filesystem -Name 'readonlyPaths' "
            "-Value $readonlyPaths",
            self.powershell,
        )

    def test_tool_runtime_readonly_grants_are_narrow(self) -> None:
        """恒久: mise、uv 実体と必要な設定ファイルへの read-only grant。

        uv の設定ディレクトリは grant せず、各 OS で uv.toml だけを加える。
        """
        for expected in ("mise_data_dir", "readonly_grants"):
            self.assertIn(expected, self.posix)
        for expected in ("$miseDataDir", "$miseExe", "$uvExe", "Get-ResolvedPathTarget"):
            self.assertIn(expected, self.powershell)
        self.assertIn("reduce $readonly_grants[] as $path", self.posix)
        self.assertIn("Add-ReadonlyDirectoryAndTarget", self.powershell)

    def test_uv_config_grants_are_one_readonly_file_and_idempotent(self) -> None:
        self.assertIn('uv_config_home="${XDG_CONFIG_HOME:-}"', self.posix)
        self.assertIn('if [[ "${uv_config_home}" != /* ]]; then', self.posix)
        self.assertIn('[[ "${HOME:-}" = /* ]] ||', self.posix)
        self.assertIn('uv_config_home="${HOME%/}/.config"', self.posix)
        self.assertIn(
            'uv_config_path="${uv_config_home%/}/uv/uv.toml"',
            self.posix,
        )
        self.assertIn('add_readonly_grant "${uv_config_path}"', self.posix)
        self.assertNotIn('add_directory_grant "${uv_config_path}"', self.posix)
        self.assertNotIn('add_readonly_grant "${uv_config_home}"', self.posix)
        self.assertNotIn('[[ -f "${uv_config_path}" ]]', self.posix)

        self.assertTrue(
            self.powershell.startswith('{{- if eq .chezmoi.os "windows" -}}')
        )
        self.assertIn(
            "$uvConfigPath = Join-Path $env:APPDATA 'uv\\uv.toml'",
            self.powershell,
        )
        self.assertIn(
            "$readonlyPaths = @(Add-UniquePath "
            "-Paths $readonlyPaths -Path $uvConfigPath)",
            self.powershell,
        )
        self.assertIn(
            "$readonlyPaths = @(\n"
            "  Get-JsonArrayOrEmpty (Get-JsonProperty -Object $existingFilesystem "
            "-Name 'readonlyPaths')\n"
            ")",
            self.powershell,
        )
        self.assertRegex(
            self.powershell,
            r"(?s)\$present = \$result \| Where-Object \{.*?"
            r"if \(-not \$present\) \{\s*\$result \+= \$Path\s*\}",
        )
        self.assertIn(
            "(Get-NormalizedPathKey -Path ([string]$_)) -eq $pathKey",
            self.powershell,
        )
        self.assertNotIn(
            "Add-ReadonlyDirectoryAndTarget -Paths $readonlyPaths -Path "
            "(Join-Path $env:APPDATA 'uv')",
            self.powershell,
        )
        self.assertNotIn("Test-Path -LiteralPath $uvConfigPath", self.powershell)
        self.assertNotIn("Get-Content -LiteralPath $uvConfigPath", self.powershell)

    def test_pinned_hook_interpreter_grants_come_from_the_recorded_runtime(self) -> None:
        """撤去単位: 固定 Python interpreter。

        撤去条件は `.github/copilot-instructions.md` の「Copilot command hook の
        固定 Python interpreter」に従う。条件が整ったら、このテストと
        hook directory / managed Python root の grant をまとめて削除する。
        """
        for expected in ("uv_python_dir", "hooks_dir", "python-runtime.env", "s/^python_root=//p"):
            self.assertIn(expected, self.posix)
        for expected in ("$uvPythonDir", "$hooksDir", "$hookRuntimeFile", "python_root="):
            self.assertIn(expected, self.powershell)
        self.assertIn('hooks_dir="${HOME}/.copilot/hooks"', self.posix)
        self.assertIn("$hooksDir = Join-Path $HOME '.copilot\\hooks'", self.powershell)
        self.assertNotIn("$hooksDir = Join-Path $copilotHome 'hooks'", self.powershell)

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

    def test_windows_uv_cache_migration_removes_only_exact_legacy_entries(self) -> None:
        """古いWindows専用cache grantと補助変数だけを移行時に除去する。"""
        self.assertIn("map(select(. != $legacy_cache))", self.posix)
        self.assertIn(
            "$legacyWindowsUvCacheDir = Join-Path",
            self.powershell,
        )
        self.assertIn(
            "'.cache\\github-copilot\\uv\\powershell-tool'",
            self.powershell,
        )
        self.assertIn("$legacyUvCachePathKeys -notcontains", self.powershell)
        self.assertIn(
            "Get-NormalizedPathKey -Path ([string]$_)",
            self.powershell,
        )
        self.assertNotIn("UV_CACHE_DIR", self.posix)
        self.assertIn(
            "$legacyUvCacheEnvironmentName = 'COPILOT_DOTFILES_UV_CACHE_DIR'",
            self.powershell,
        )
        self.assertIn(
            "[EnvironmentVariableTarget]::User",
            self.powershell,
        )
        self.assertIn("[EnvironmentVariableTarget]::Process", self.powershell)
        self.assertIn("$null,", self.powershell)
        self.assertNotIn("$uvCacheDir", self.powershell)
        self.assertNotIn("Get-SafeWindowsUvCache", self.powershell)
        self.assertNotIn("Test-PathOverlap", self.powershell)
        self.assertNotIn("New-Item -ItemType Directory -Path $uvCacheDir", self.powershell)
        self.assertNotIn("Add-UniquePath -Paths $readwritePaths -Path $uvCacheDir", self.powershell)
        self.assertNotIn(
            "Remove-Item -LiteralPath $legacyWindowsUvCacheDir",
            self.powershell,
        )
        self.assertIn(
            "(Get-NormalizedPathKey -Path $legacyUserCacheValue) -eq",
            self.powershell,
        )
        self.assertIn("Publish-EnvironmentChange", self.powershell)
        self.assertNotIn('mkdir -p "${uv_cache_dir}"', self.posix)


if __name__ == "__main__":
    unittest.main()
