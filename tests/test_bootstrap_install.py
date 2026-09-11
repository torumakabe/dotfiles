"""Verify the cross-platform chezmoi bootstrap entrypoint."""

import os
import pathlib
import subprocess
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALL_SCRIPT = REPO_ROOT / "install.sh"


@unittest.skipIf(os.name == "nt", "the bootstrap script requires a POSIX shell")
class BootstrapInstallTests(unittest.TestCase):
    def test_download_is_bounded_and_retried(self) -> None:
        source = INSTALL_SCRIPT.read_text(encoding="utf-8")
        for option in (
            "--connect-timeout 15",
            "--max-time 120",
            "--retry 3",
            "--retry-delay 2",
            "--timeout=120",
            "--tries=4",
        ):
            with self.subTest(option=option):
                self.assertIn(option, source)

    def _run_with_fake_chezmoi(self, branch: str | None) -> list[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            arguments_path = root / "arguments.txt"
            fake_chezmoi = bin_dir / "chezmoi"
            fake_chezmoi.write_text(
                """#!/bin/sh
printf '%s\\n' "$@" >"$CHEZMOI_ARGUMENTS"
""",
                encoding="utf-8",
            )
            fake_chezmoi.chmod(0o755)

            env = os.environ.copy()
            env.update({
                "PATH": f"{bin_dir}:{env['PATH']}",
                "CHEZMOI_ARGUMENTS": str(arguments_path),
            })
            if branch is None:
                env.pop("CHEZMOI_INIT_BRANCH", None)
            else:
                env["CHEZMOI_INIT_BRANCH"] = branch

            result = subprocess.run(
                ["/bin/sh", str(INSTALL_SCRIPT)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return arguments_path.read_text(encoding="utf-8").splitlines()

    def test_default_init_uses_repository_default_branch(self) -> None:
        self.assertEqual(
            self._run_with_fake_chezmoi(None),
            ["init", "--apply", "torumakabe"],
        )

    def test_init_branch_is_forwarded_to_chezmoi(self) -> None:
        self.assertEqual(
            self._run_with_fake_chezmoi("feature/test"),
            [
                "init",
                "--apply",
                "--branch",
                "feature/test",
                "torumakabe",
            ],
        )
