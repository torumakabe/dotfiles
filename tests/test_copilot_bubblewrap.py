"""Pin the Linux bubblewrap install and warning-only diagnostics."""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
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


def _run_diagnostics(
    root: pathlib.Path, settings: dict | None
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    copilot_home = root / "copilot"
    copilot_home.mkdir()
    if settings is not None:
        (copilot_home / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )

    fake_bin = root / "bin"
    fake_bin.mkdir()
    bwrap_log = root / "bwrap.log"
    fake_bwrap = fake_bin / "bwrap"
    fake_bwrap.write_text(
        """#!/usr/bin/env bash
printf '%s\n' "$*" >>"${BWRAP_LOG}"
if [ "${1:-}" = "--version" ]; then
  echo "bubblewrap 0.8.0"
fi
""",
        encoding="utf-8",
    )
    fake_bwrap.chmod(0o755)

    script_path = root / "check-sandbox.sh"
    script_path.write_text(_render("linux"), encoding="utf-8")
    result = subprocess.run(
        ["bash", str(script_path)],
        env={
            **os.environ,
            "BWRAP_LOG": str(bwrap_log),
            "COPILOT_HOME": str(copilot_home),
            "HOME": str(root),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        },
        check=False,
        capture_output=True,
        encoding="utf-8",
    )
    calls = (
        bwrap_log.read_text(encoding="utf-8").splitlines()
        if bwrap_log.exists()
        else []
    )
    return result, calls


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
        self.assertNotIn("approved bypass", script)
        self.assertIn("'/sandbox status'", script)
        self.assertIn("'/sandbox disable'", script)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class CopilotBubblewrapTemplateTests(unittest.TestCase):
    def test_diagnostics_render_only_for_linux(self) -> None:
        self.assertIn("bwrap --version", _render("linux"))
        self.assertEqual(_render("darwin"), "")
        self.assertEqual(_render("windows"), "")

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux CI")
    def test_disabled_sandbox_skips_bubblewrap_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory(
            dir=REPO_ROOT, prefix=".test-copilot-bubblewrap-"
        ) as temp_dir:
            result, calls = _run_diagnostics(
                pathlib.Path(temp_dir), {"sandbox": {"enabled": False}}
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux CI")
    def test_enabled_or_unset_sandbox_runs_bubblewrap_diagnostics(self) -> None:
        cases = {
            "enabled": {"sandbox": {"enabled": True}},
            "key-unset": {"sandbox": {}},
            "settings-missing": None,
        }
        for name, settings in cases.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory(
                    dir=REPO_ROOT, prefix=".test-copilot-bubblewrap-"
                ) as temp_dir:
                    result, calls = _run_diagnostics(
                        pathlib.Path(temp_dir), settings
                    )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(
                    any(call == "--version" for call in calls), calls
                )
                self.assertTrue(
                    any(call.startswith("--unshare-user ") for call in calls),
                    calls,
                )


if __name__ == "__main__":
    unittest.main()
