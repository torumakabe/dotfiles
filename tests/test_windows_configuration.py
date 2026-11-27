"""Validate declarative Windows package-management safeguards."""

import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "reference/windows/configuration.dsc.yaml"
OPERATIONS_PATH = REPO_ROOT / "docs/operations.md"


class WindowsConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = CONFIG_PATH.read_text(encoding="utf-8")
        cls.operations = OPERATIONS_PATH.read_text(encoding="utf-8")

    def test_self_updated_packages_are_followed_by_integrated_blocking_pins(
        self,
    ) -> None:
        resource_ids = (
            "GitHubCopilotCli",
            "GitHubCopilotApp",
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

    def _pin_scripts(self) -> dict[str, str]:
        start = self.config.index("id: SelfUpdatedPackageBlockingPins")
        end = self.config.index("\n    - resource:", start)
        block = self.config[start:end]
        scripts = {}
        for match in re.finditer(
            r"(?m)^        (GetScript|TestScript|SetScript): \|\n((?:          .*\n|\n)+)",
            block + "\n",
        ):
            scripts[match.group(1)] = match.group(2)
        self.assertEqual(set(scripts), {"GetScript", "TestScript", "SetScript"})
        return scripts

    def test_pin_scripts_share_managed_pins_and_parser(self) -> None:
        scripts = self._pin_scripts()
        managed = {
            name: re.findall(r"@\{ Id = '([^']+)'; Pinned = (\$true|\$false) \}", body)
            for name, body in scripts.items()
        }
        self.assertTrue(managed["GetScript"])
        self.assertEqual(managed["GetScript"], managed["TestScript"])
        self.assertEqual(managed["GetScript"], managed["SetScript"])

        parser = re.compile(r"(?ms)^ *function Get-WinGetPinType \{.*?^          \}$")
        test_parser = parser.search(scripts["TestScript"])
        set_parser = parser.search(scripts["SetScript"])
        self.assertIsNotNone(test_parser)
        self.assertIsNotNone(set_parser)
        self.assertEqual(test_parser.group(0), set_parser.group(0))
        # ID 列の 2 つ後ろが source 列。末尾列や ID の部分一致では判定しない。
        self.assertIn("$columns[$idx + 2] -eq 'winget'", test_parser.group(0))
        self.assertIn("return $columns[$idx + 3]", test_parser.group(0))

        for body in scripts.values():
            self.assertIn("winget pin list --source winget", body)

    def test_pinned_ids_are_installed_and_documented(self) -> None:
        scripts = self._pin_scripts()
        pinned_ids = set(
            re.findall(r"@\{ Id = '([^']+)'; Pinned = \$true \}", scripts["GetScript"])
        )
        installed_ids = set(
            re.findall(
                r"(?m)^      settings:\n        id: (\S+)\n        source: winget$",
                self.config,
            )
        )
        documented_ids = set(
            re.findall(r"^\| `([^`]+)` \| .* \| あり \|$", self.operations, re.MULTILINE)
        )
        self.assertTrue(pinned_ids)
        self.assertLessEqual(pinned_ids, installed_ids)
        self.assertEqual(pinned_ids, documented_ids)

    def test_set_script_converges_to_test_script_conditions(self) -> None:
        scripts = self._pin_scripts()
        test_script = scripts["TestScript"]
        set_script = scripts["SetScript"]

        # TestScript が false を返す条件と、SetScript が変更せず skip する条件が補集合になる。
        self.assertIn("if ($pin.Pinned -and $pinType -ne 'Blocking') {\n", test_script)
        self.assertIn("if (-not $pin.Pinned -and $null -ne $pinType) {\n", test_script)
        self.assertIn("if ($pin.Pinned -and $pinType -eq 'Blocking') {\n", set_script)
        self.assertIn("if (-not $pin.Pinned -and $null -eq $pinType) {\n", set_script)
        self.assertRegex(test_script, r"if \(\$LASTEXITCODE -ne 0\) \{\n\s+return \$false")
        self.assertRegex(set_script, r"if \(\$LASTEXITCODE -ne 0\) \{\n\s+throw ")

        remove = set_script.index(
            "winget pin remove --id $pin.Id --exact --source winget"
        )
        add = set_script.index(
            "winget pin add --id $pin.Id --exact --source winget --blocking"
        )
        self.assertLess(remove, add)
        self.assertGreaterEqual(set_script.count("$failures.Add("), 2)
        self.assertIn(
            'throw "Failed to converge WinGet pins: $($failures -join \'; \')"',
            set_script,
        )


if __name__ == "__main__":
    unittest.main()
