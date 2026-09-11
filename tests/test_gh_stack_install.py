"""Verify official gh-stack extension and skill installation."""

import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SHELL_INSTALLER = REPO_ROOT / "home/run_after_31-install-gh-stack.sh.tmpl"
POWERSHELL_INSTALLER = REPO_ROOT / "home/run_after_31-install-gh-stack.ps1.tmpl"
CHEZMOIIGNORE = REPO_ROOT / "home/.chezmoiignore"
README = REPO_ROOT / "README.md"


class GhStackInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.shell = SHELL_INSTALLER.read_text(encoding="utf-8")
        cls.powershell = POWERSHELL_INSTALLER.read_text(encoding="utf-8")
        cls.ignore = CHEZMOIIGNORE.read_text(encoding="utf-8")

    def test_both_installers_target_the_official_repository(self) -> None:
        normalized_shell = " ".join(
            self.shell.replace("\\\n", " ").split()
        )
        normalized_powershell = " ".join(self.powershell.split())

        self.assertIn('"${gh_path}" extension list', self.shell)
        self.assertIn('gh_path="$(mise which gh 2>/dev/null)"', self.shell)
        self.assertIn(
            "install_from_public_github extension install github/gh-stack",
            normalized_shell,
        )
        self.assertIn(
            '"${gh_path}" skill list --agent github-copilot --scope user',
            normalized_shell,
        )
        self.assertIn(
            "install_from_public_github skill install github/gh-stack gh-stack "
            "--agent github-copilot --scope user",
            normalized_shell,
        )

        self.assertIn("& $ghPath extension list", self.powershell)
        self.assertIn("$ghPath = & mise which gh", self.powershell)
        self.assertIn(
            "'extension', 'install', 'github/gh-stack'",
            normalized_powershell,
        )
        self.assertIn(
            "& $ghPath skill list --agent github-copilot --scope user",
            normalized_powershell,
        )
        self.assertRegex(
            normalized_powershell,
            r"'skill', 'install', 'github/gh-stack', 'gh-stack'.*"
            r"'--agent', 'github-copilot'.*'--scope', 'user'",
        )

    def test_both_installers_skip_updates(self) -> None:
        for name, source in (
            ("shell", self.shell),
            ("powershell", self.powershell),
        ):
            with self.subTest(installer=name):
                self.assertNotIn("extension upgrade", source)
                self.assertNotIn("skill update", source)
                self.assertNotIn("--force", source)

    def test_both_installers_retry_public_repository_without_credentials(self) -> None:
        self.assertIn("install_from_public_github", self.shell)
        self.assertIn("-u GH_TOKEN", self.shell)
        self.assertIn("-u GITHUB_TOKEN", self.shell)
        self.assertIn('GH_CONFIG_DIR="${anonymous_config}"', self.shell)

        self.assertIn("Invoke-GhPublicInstall", self.powershell)
        self.assertIn(
            "SetEnvironmentVariable('GH_TOKEN', $null)",
            self.powershell,
        )
        self.assertIn(
            "SetEnvironmentVariable('GITHUB_TOKEN', $null)",
            self.powershell,
        )
        self.assertIn("$env:GH_CONFIG_DIR = $anonymousConfig", self.powershell)

    @unittest.skipIf(os.name == "nt", "the POSIX installer requires Bash")
    def test_shell_retries_failed_installs_anonymously(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            awk_path = shutil.which("awk")
            self.assertIsNotNone(awk_path)
            (bin_dir / "awk").symlink_to(awk_path)
            log_path = root / "calls.log"
            fake_gh = bin_dir / "gh"
            fake_gh.write_text(
                """#!/usr/bin/env bash
set -u
printf '%s|config=%s|gh=%s|github=%s\\n' \
  "$*" "${GH_CONFIG_DIR-}" "${GH_TOKEN-}" "${GITHUB_TOKEN-}" \
  >>"${GH_TEST_LOG}"
case "$1 $2" in
  "extension list"|"skill list")
    exit 0
    ;;
  "extension install"|"skill install")
    if [ -n "${GH_CONFIG_DIR-}" ] &&
       [ -z "${GH_TOKEN-}" ] &&
       [ -z "${GITHUB_TOKEN-}" ]; then
      exit 0
    fi
    exit 1
    ;;
esac
exit 1
""",
                encoding="utf-8",
            )
            fake_gh.chmod(0o755)

            env = os.environ.copy()
            env.update({
                "PATH": f"{bin_dir}:{env['PATH']}",
                "GH_TEST_LOG": str(log_path),
                "GH_TOKEN": "authenticated-token",
                "GITHUB_TOKEN": "secondary-token",
            })
            result = subprocess.run(
                ["bash", str(SHELL_INSTALLER)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            calls = log_path.read_text(encoding="utf-8").splitlines()
            anonymous_installs = [
                line for line in calls
                if " install " in line
                and "|config=" in line
                and "|gh=|github=" in line
            ]
            self.assertEqual(len(anonymous_installs), 2, calls)

    @unittest.skipIf(os.name == "nt", "the POSIX installer requires Bash")
    def test_shell_uses_mise_managed_gh_before_path_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            awk_path = shutil.which("awk")
            self.assertIsNotNone(awk_path)
            (bin_dir / "awk").symlink_to(awk_path)
            log_path = root / "calls.log"
            managed_gh = root / "managed-gh"
            managed_gh.write_text(
                """#!/bin/bash
printf '%s\\n' "$*" >>"${GH_TEST_LOG}"
case "$1 $2" in
  "extension list")
    printf 'gh-stack github/gh-stack v0.1.1\\n'
    ;;
  "skill list")
    printf 'gh-stack\\n'
    ;;
esac
""",
                encoding="utf-8",
            )
            managed_gh.chmod(0o755)
            fake_mise = bin_dir / "mise"
            fake_mise.write_text(
                f"""#!/bin/bash
if [ "$1 $2" = "which gh" ]; then
  printf '%s\\n' '{managed_gh}'
  exit 0
fi
exit 1
""",
                encoding="utf-8",
            )
            fake_mise.chmod(0o755)

            env = os.environ.copy()
            env.update({
                "PATH": str(bin_dir),
                "GH_TEST_LOG": str(log_path),
            })
            result = subprocess.run(
                ["/bin/bash", str(SHELL_INSTALLER)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                log_path.read_text(encoding="utf-8").splitlines(),
                [
                    "extension list",
                    "skill list --agent github-copilot --scope user "
                    "--json skillName --jq "
                    '.[] | select(.skillName == "gh-stack") | .skillName',
                ],
            )

    def test_installed_skill_skips_installation(self) -> None:
        shell = " ".join(self.shell.split())
        powershell = " ".join(self.powershell.split())

        self.assertIn(
            'if [ "${installed_skill}" = "gh-stack" ]; then exit 0 fi',
            shell,
        )
        self.assertIn("if ($skill) { exit 0 }", powershell)

    def test_installers_require_skill_inventory_support(self) -> None:
        for name, source in (
            ("shell", self.shell),
            ("powershell", self.powershell),
        ):
            with self.subTest(installer=name):
                self.assertIn("GitHub CLI 2.94 or later is required", source)

    def test_missing_gh_warns_and_exits_successfully(self) -> None:
        self.assertIn('gh_path="$(command -v gh', self.shell)
        self.assertIn('gh_path="$(mise which gh', self.shell)
        self.assertRegex(
            self.shell,
            r"(?s)if gh_path=.*?elif command -v mise.*?else.*?Warning:.*?exit 0",
        )
        self.assertIn(
            "Get-Command gh -ErrorAction SilentlyContinue",
            self.powershell,
        )
        self.assertIn("Get-Command mise -ErrorAction SilentlyContinue", self.powershell)
        self.assertRegex(
            self.powershell,
            r"(?s)if \(\$ghCommand\).*?elseif \(Get-Command mise.*?"
            r"if \(-not \$ghPath\).*?Write-Warning.*?exit 0",
        )

    def test_installers_are_run_after_scripts_for_their_platform(self) -> None:
        self.assertTrue(SHELL_INSTALLER.name.startswith("run_after_"))
        self.assertTrue(POWERSHELL_INSTALLER.name.startswith("run_after_"))
        self.assertIn("run_after_31-", SHELL_INSTALLER.name)
        self.assertIn("run_after_31-", POWERSHELL_INSTALLER.name)
        self.assertNotIn(b"\r\n", SHELL_INSTALLER.read_bytes())

        non_windows_blocks = re.findall(
            r'{{ if ne \.chezmoi\.os "windows" -}}(.*?){{ end -}}',
            self.ignore,
            re.DOTALL,
        )
        windows_blocks = re.findall(
            r'{{ if eq \.chezmoi\.os "windows" -}}(.*?){{ end -}}',
            self.ignore,
            re.DOTALL,
        )
        self.assertTrue(
            any(
                "31-install-gh-stack.ps1" in block
                for block in non_windows_blocks
            )
        )
        self.assertTrue(
            any(
                "31-install-gh-stack.sh" in block
                for block in windows_blocks
            )
        )
        self.assertNotIn("run_after_31-install-gh-stack", self.ignore)

    def test_first_setup_reapplies_after_gh_is_available(self) -> None:
        readme = README.read_text(encoding="utf-8")
        devcontainer = readme[
            readme.index("### Dev Container (ローカル)") : readme.index(
                "### Windows"
            )
        ]
        windows = readme[
            readme.index("### Windows") : readme.index("## 日常操作")
        ]

        self.assertLess(
            devcontainer.index("mise install --yes"),
            devcontainer.index("chezmoi apply"),
        )
        self.assertNotIn("chezmoi init --apply", windows)
        auth_and_apply = "gh auth login\nchezmoi apply"
        self.assertIn(auth_and_apply, windows)
        for earlier, later in (
            ("chezmoi init torumakabe", "winget configure"),
            ("winget configure", auth_and_apply),
            (auth_and_apply, "PowerShell Profile"),
        ):
            with self.subTest(earlier=earlier, later=later):
                self.assertLess(windows.index(earlier), windows.index(later))
        self.assertIn(
            'if (Test-Path "$env:USERPROFILE\\PowerShell_profile.ps1")',
            windows,
        )
        self.assertIn("$legacyLine", windows)


if __name__ == "__main__":
    unittest.main()
