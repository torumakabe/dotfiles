"""Pin the Linux bubblewrap install and warning-only diagnostics."""

import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "home"
PACKAGE_SCRIPT_PATH = SOURCE_ROOT / "run_once_before_10-install-packages.sh.tmpl"
DIAGNOSTIC_SCRIPT_PATH = SOURCE_ROOT / "run_after_45-check-copilot-sandbox.sh.tmpl"

class CopilotBubblewrapSourceTests(unittest.TestCase):
    def test_linux_package_list_installs_bubblewrap(self) -> None:
        script = PACKAGE_SCRIPT_PATH.read_text(encoding="utf-8")
        start = script.index("sudo apt-get install -y -qq \\")
        install_block = script[start:script.index("\n\n", start)]
        self.assertRegex(install_block, r"\bbubblewrap\b")

    def test_diagnostics_are_generated_only_for_linux(self) -> None:
        script = DIAGNOSTIC_SCRIPT_PATH.read_text(encoding="utf-8").strip()
        self.assertTrue(script.startswith('{{- if eq .chezmoi.os "linux" -}}'))
        self.assertTrue(script.endswith("{{- end -}}"))


if __name__ == "__main__":
    unittest.main()
