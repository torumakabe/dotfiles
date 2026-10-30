"""Guard static Copilot sandbox configuration contracts."""

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "home"
POSIX_SCRIPT_PATH = SOURCE_ROOT / "run_after_35-configure-copilot-sandbox.sh.tmpl"
POWERSHELL_SCRIPT_PATH = (
    SOURCE_ROOT / "run_onchange_after_35-configure-copilot-sandbox.ps1.tmpl"
)
ZSHRC_PATH = SOURCE_ROOT / "dot_zshrc.tmpl"
POSIX_PROFILE_PATH = SOURCE_ROOT / "dot_profile.tmpl"
POWERSHELL_PROFILE_PATH = SOURCE_ROOT / "PowerShell_profile.ps1.tmpl"

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


@unittest.skipUnless(
    sys.platform == "darwin" and shutil.which("chezmoi"),
    "macOS and chezmoi are required for profile environment tests",
)
class MacOSDotnetBundleEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.profile_path = pathlib.Path(cls.temp_dir.name) / "profile"
        template_path = SOURCE_ROOT / "dot_profile.tmpl"
        cls.profile_path.write_text(
            cls._render_profile(template_path, "darwin"),
            encoding="utf-8",
        )
        cls.linux_profile = cls._render_profile(template_path, "linux")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    @staticmethod
    def _render_profile(template_path: pathlib.Path, os_name: str) -> str:
        result = subprocess.run(
            [
                "chezmoi",
                "execute-template",
                "--override-data",
                json.dumps({"chezmoi": {"os": os_name}}),
                "--file",
                str(template_path),
            ],
            check=False,
            capture_output=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        return result.stdout

    def _run_profile(
        self,
        *,
        tmpdir: str | None = None,
        dotnet_base: str | None = None,
        set_dotnet_base: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("__DOTFILES_PROFILE_LOADED", None)
        env.pop("DOTNET_BUNDLE_EXTRACT_BASE_DIR", None)
        if tmpdir is None:
            env.pop("TMPDIR", None)
        else:
            env["TMPDIR"] = tmpdir
        if set_dotnet_base:
            env["DOTNET_BUNDLE_EXTRACT_BASE_DIR"] = dotnet_base or ""

        return subprocess.run(
            [
                "/bin/sh",
                "-c",
                '. "$1"; . "$1"; '
                'if [ "${DOTNET_BUNDLE_EXTRACT_BASE_DIR+x}" = x ]; then '
                'printf "SET:%s\\n" "$DOTNET_BUNDLE_EXTRACT_BASE_DIR"; '
                'else printf "UNSET\\n"; fi',
                "profile-test",
                str(self.profile_path),
            ],
            check=False,
            capture_output=True,
            encoding="utf-8",
            env=env,
        )

    def test_profile_sets_default_only_for_private_macos_tmpdir(self) -> None:
        private_tmpdir = os.environ["TMPDIR"]
        result = self._run_profile(tmpdir=private_tmpdir)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            f"SET:{pathlib.Path(private_tmpdir).resolve()}",
        )
        self.assertEqual(result.stderr, "")
        self.assertNotIn("DOTNET_BUNDLE_EXTRACT_BASE_DIR", self.linux_profile)

    def test_existing_nonempty_and_empty_values_are_preserved(self) -> None:
        for value in ("/existing/dotnet-cache", ""):
            with self.subTest(value=value):
                result = self._run_profile(
                    tmpdir="/tmp",
                    dotnet_base=value,
                    set_dotnet_base=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), f"SET:{value}")

    def test_shared_or_missing_tmpdir_does_not_set_a_default(self) -> None:
        for tmpdir in ("/tmp", None):
            with self.subTest(tmpdir=tmpdir):
                result = self._run_profile(tmpdir=tmpdir)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "UNSET")
                self.assertIn("not a private user temporary directory", result.stderr)


if __name__ == "__main__":
    unittest.main()
