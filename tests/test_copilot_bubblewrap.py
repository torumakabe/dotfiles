"""Pin the Linux bubblewrap install and warning-only diagnostics."""

import json
import pathlib
import shutil
import subprocess
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "home"
PACKAGE_SCRIPT_PATH = SOURCE_ROOT / "run_once_before_10-install-packages.sh.tmpl"
DIAGNOSTIC_SCRIPT_PATH = SOURCE_ROOT / "run_after_45-check-copilot-sandbox.sh.tmpl"


def _render(platform: str) -> str:
    result = subprocess.run(
        [
            "chezmoi",
            "--source",
            str(SOURCE_ROOT),
            "execute-template",
            "--override-data",
            json.dumps({"chezmoi": {"os": platform, "arch": "amd64"}}),
            "--file",
            str(DIAGNOSTIC_SCRIPT_PATH),
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return result.stdout


class CopilotBubblewrapSourceTests(unittest.TestCase):
    def test_linux_package_list_installs_bubblewrap(self) -> None:
        script = PACKAGE_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("  bubblewrap \\\n", script)

    def test_diagnostics_are_warning_only(self) -> None:
        script = DIAGNOSTIC_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("set -uo pipefail", script)
        self.assertNotIn("set -euo pipefail", script)
        self.assertIn("bwrap --version", script)
        self.assertIn('dpkg --compare-versions "${bwrap_version}" ge "0.5.0"', script)
        self.assertIn("/proc/sys/kernel/unprivileged_userns_clone", script)
        self.assertIn("/proc/sys/user/max_user_namespaces", script)
        self.assertIn("bwrap --unshare-user", script)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class CopilotBubblewrapTemplateTests(unittest.TestCase):
    def test_diagnostics_render_only_for_linux(self) -> None:
        self.assertIn("bwrap --version", _render("linux"))
        self.assertEqual(_render("darwin"), "")
        self.assertEqual(_render("windows"), "")


if __name__ == "__main__":
    unittest.main()
