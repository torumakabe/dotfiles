"""Validate declarative Windows package-management safeguards."""

import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "reference/windows/configuration.dsc.yaml"


class WindowsConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = CONFIG_PATH.read_text(encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()
