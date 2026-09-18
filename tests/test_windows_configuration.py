"""Validate declarative Windows package-management safeguards."""

import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "reference/windows/configuration.dsc.yaml"
README_PATH = REPO_ROOT / "README.md"
TROUBLESHOOTING_PATH = REPO_ROOT / "docs/troubleshooting.md"


class WindowsConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = CONFIG_PATH.read_text(encoding="utf-8")
        cls.readme = README_PATH.read_text(encoding="utf-8")
        cls.troubleshooting = TROUBLESHOOTING_PATH.read_text(encoding="utf-8")

    def test_copilot_app_install_is_followed_by_blocking_pin(self) -> None:
        package_id = "id: GitHubCopilotApp"
        pin_id = "id: GitHubCopilotAppBlockingPin"

        self.assertIn(package_id, self.config)
        self.assertIn("id: GitHub.CopilotApp", self.config)
        self.assertIn("resource: PSDscResources/Script", self.config)
        self.assertIn(pin_id, self.config)
        self.assertLess(self.config.index(package_id), self.config.index(pin_id))
        self.assertIn(
            "dependsOn:\n        - GitHubCopilotApp",
            self.config[self.config.index(pin_id) :],
        )

    def test_copilot_app_pin_converges_to_blocking(self) -> None:
        pin_block = self.config[
            self.config.index("id: GitHubCopilotAppBlockingPin") :
            self.config.index(
                "resource: Microsoft.WinGet.DSC/WinGetPackage",
                self.config.index("id: GitHubCopilotAppBlockingPin"),
            )
        ]

        self.assertIn(
            "winget pin list --id GitHub.CopilotApp --exact --source winget",
            pin_block,
        )
        self.assertIn(r"GitHub\.CopilotApp", pin_block)
        self.assertIn("Blocking", pin_block)
        self.assertIn(
            "winget pin remove --id GitHub.CopilotApp --exact --source winget",
            pin_block,
        )
        self.assertIn(
            "winget pin add --id GitHub.CopilotApp --exact --source winget --blocking",
            pin_block,
        )
        self.assertIn(
            'throw "Failed to add a blocking WinGet pin for GitHub.CopilotApp."',
            pin_block,
        )

    def test_visual_studio_workload_avoids_broken_elevated_units(self) -> None:
        build_tools_start = self.config.index("id: VisualStudioBuildTools")
        workload_start = self.config.index("id: VisualStudioVCTools")
        workload_end = self.config.index(
            "resource: Microsoft.WinGet.DSC/WinGetPackage",
            workload_start,
        )
        workload_block = self.config[workload_start:workload_end]

        self.assertLess(build_tools_start, workload_start)
        self.assertNotIn("securityContext: elevated", self.config)
        self.assertIn(
            "dependsOn:\n        - VisualStudioBuildTools",
            workload_block,
        )
        self.assertIn(
            "-requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            workload_block,
        )
        self.assertIn(
            r"-find 'VC\Tools\MSVC\**\bin\Hostx64\x64\link.exe'",
            workload_block,
        )
        self.assertIn(
            "Start-Process -FilePath $setup -Verb RunAs",
            workload_block,
        )
        self.assertIn(
            "'--add', 'Microsoft.VisualStudio.Workload.VCTools'",
            workload_block,
        )
        self.assertIn("$null -eq $process.ExitCode", workload_block)
        self.assertIn(
            "requires approval of the UAC prompt in an interactive Windows session",
            workload_block,
        )
        self.assertIn("$process.ExitCode -eq 3010", workload_block)
        self.assertIn("Write-Warning", workload_block)
        self.assertNotIn("862968", workload_block)
        self.assertNotIn("Microsoft.VisualStudio.DSC/VSComponents", self.config)

    def test_windows_configuration_requires_normal_interactive_powershell(self) -> None:
        old_instruction = "管理者権限の PowerShell で"

        self.assertNotIn(old_instruction, self.config)
        self.assertNotIn(old_instruction, self.troubleshooting)
        self.assertIn("通常の対話型 PowerShell", self.config)
        self.assertIn("通常の対話型 PowerShell", self.readme)
        self.assertIn("通常の対話型 PowerShell", self.troubleshooting)


if __name__ == "__main__":
    unittest.main()
