"""Verify official gh-stack extension and skill installation."""

import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SHELL_INSTALLER = REPO_ROOT / "home/run_after_31-install-gh-stack.sh.tmpl"
POWERSHELL_INSTALLER = REPO_ROOT / "home/run_after_31-install-gh-stack.ps1.tmpl"
CHEZMOIIGNORE = REPO_ROOT / "home/.chezmoiignore"
README = REPO_ROOT / "README.md"
UPSTREAM_REPOSITORY = "github/gh-stack"
SKILL_INSTALL_COMMAND = (
    "gh skill install github/gh-stack gh-stack "
    "--agent github-copilot --scope user"
)


class GhStackInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.shell = SHELL_INSTALLER.read_text(encoding="utf-8")
        cls.powershell = POWERSHELL_INSTALLER.read_text(encoding="utf-8")
        cls.ignore = CHEZMOIIGNORE.read_text(encoding="utf-8")

    def test_both_installers_target_the_official_repository(self) -> None:
        extension_install_command = (
            f"gh extension install {UPSTREAM_REPOSITORY}"
        )
        for name, source in (
            ("shell", self.shell),
            ("powershell", self.powershell),
        ):
            with self.subTest(installer=name):
                normalized = " ".join(source.replace("\\\n", " ").split())
                self.assertIn("gh extension list", source)
                self.assertIn(extension_install_command, source)
                self.assertIn(
                    "gh skill list --agent github-copilot --scope user",
                    normalized,
                )
                self.assertIn(SKILL_INSTALL_COMMAND, normalized)
                self.assertLess(
                    source.index("gh extension list"),
                    source.index(extension_install_command),
                )
                self.assertLess(
                    source.index("gh skill list"),
                    source.index(SKILL_INSTALL_COMMAND),
                )

    def test_both_installers_skip_updates(self) -> None:
        for name, source in (
            ("shell", self.shell),
            ("powershell", self.powershell),
        ):
            with self.subTest(installer=name):
                self.assertNotIn("extension upgrade", source)
                self.assertNotIn("skill update", source)
                self.assertEqual(
                    source.count(
                        f"gh extension install {UPSTREAM_REPOSITORY}"
                    ),
                    1,
                )
                self.assertEqual(source.count(SKILL_INSTALL_COMMAND), 1)
                self.assertNotIn("--force", source)

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
        self.assertIn("if ! command -v gh", self.shell)
        self.assertRegex(
            self.shell,
            r"(?s)if ! command -v gh.*?Warning:.*?exit 0",
        )
        self.assertIn(
            "Get-Command gh -ErrorAction SilentlyContinue",
            self.powershell,
        )
        self.assertRegex(
            self.powershell,
            r"(?s)if \(-not \(Get-Command gh.*?Write-Warning.*?exit 0",
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
