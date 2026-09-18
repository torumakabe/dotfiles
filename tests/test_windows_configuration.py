"""Validate declarative Windows package-management safeguards."""

import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "reference/windows/configuration.dsc.yaml"
README_PATH = REPO_ROOT / "README.md"
OPERATIONS_PATH = REPO_ROOT / "docs/operations.md"
TROUBLESHOOTING_PATH = REPO_ROOT / "docs/troubleshooting.md"


class WindowsConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = CONFIG_PATH.read_text(encoding="utf-8")
        cls.readme = README_PATH.read_text(encoding="utf-8")
        cls.operations = OPERATIONS_PATH.read_text(encoding="utf-8")
        cls.troubleshooting = TROUBLESHOOTING_PATH.read_text(encoding="utf-8")

    def test_self_updated_packages_are_followed_by_integrated_blocking_pins(
        self,
    ) -> None:
        resource_ids = (
            "GitHubCopilotCli",
            "GitHubCopilotApp",
            "Mise",
            "Rustup",
        )
        pin_id = "id: SelfUpdatedPackageBlockingPins"

        self.assertIn("resource: PSDscResources/Script", self.config)
        self.assertIn(pin_id, self.config)
        for resource_id in resource_ids:
            package_id = f"id: {resource_id}"
            self.assertIn(package_id, self.config)
            self.assertLess(self.config.index(package_id), self.config.index(pin_id))
            self.assertIn(
                f"        - {resource_id}",
                self.config[self.config.index(pin_id) :],
            )

    def test_integrated_pin_policy_converges_both_desired_states(self) -> None:
        pin_block = self.config[
            self.config.index("id: SelfUpdatedPackageBlockingPins") :
            self.config.index(
                "resource: Microsoft.WinGet.DSC/WinGetPackage",
                self.config.index("id: SelfUpdatedPackageBlockingPins"),
            )
        ]

        expected_ids = {
            "GitHub.CopilotApp",
            "GitHub.Copilot",
            "jdx.mise",
            "Rustlang.Rustup",
        }
        configured_ids = re.findall(
            r"@\{ Id = '([^']+)'; Pinned = \$true \}",
            pin_block,
        )
        self.assertEqual(set(configured_ids), expected_ids)
        self.assertEqual(len(configured_ids), len(expected_ids) * 3)
        self.assertNotIn("Microsoft.Azd", pin_block)
        self.assertIn(
            "winget pin list --source winget",
            pin_block,
        )
        self.assertNotIn("winget pin list --id", pin_block)
        self.assertIn("[array]::IndexOf($columns, $Id)", pin_block)
        self.assertIn("$columns[$idx + 2] -eq 'winget'", pin_block)
        self.assertIn("return $columns[$idx + 3]", pin_block)
        self.assertNotIn("$columns[-1]", pin_block)
        self.assertNotIn(r"GitHub\.Copilot", pin_block)
        self.assertIn("$pin.Pinned -and $pinType -ne 'Blocking'", pin_block)
        self.assertIn("-not $pin.Pinned -and $null -ne $pinType", pin_block)
        self.assertIn("-not $pin.Pinned -and $null -eq $pinType", pin_block)
        self.assertIn(
            "winget pin remove --id $pin.Id --exact --source winget",
            pin_block,
        )
        self.assertIn(
            "winget pin add --id $pin.Id --exact --source winget --blocking",
            pin_block,
        )
        self.assertIn("$failures.Add(\"$($pin.Id):", pin_block)
        self.assertIn(
            'throw "Failed to converge WinGet pins: $($failures -join \'; \')"',
            pin_block,
        )

    def test_operations_document_matches_integrated_pin_policy(self) -> None:
        expected_ids = {
            "GitHub.CopilotApp",
            "GitHub.Copilot",
            "jdx.mise",
            "Rustlang.Rustup",
        }
        documented_ids = set(
            re.findall(r"^\| `([^`]+)` \| .* \| あり \|$", self.operations, re.MULTILINE)
        )
        self.assertEqual(documented_ids, expected_ids)
        self.assertIn("`Microsoft.Azd`", self.operations)
        self.assertIn("`winget upgrade --all`", self.operations)
        self.assertIn("管理していないパッケージの結果は保証しない", self.operations)
        self.assertIn("`Pinned = false`", self.operations)
        self.assertIn(
            "Windows の pin を転用できるとは仮定せず",
            (REPO_ROOT / "docs/adr/032-protect-self-updated-winget-packages-with-blocking-pins.md").read_text(
                encoding="utf-8"
            ),
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
