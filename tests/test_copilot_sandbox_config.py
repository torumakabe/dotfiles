"""Guard static GitHub Copilot sandbox configuration contracts."""

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
    SOURCE_ROOT / "run_after_35-configure-copilot-sandbox.ps1.tmpl"
)
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

if __name__ == "__main__":
    unittest.main()
