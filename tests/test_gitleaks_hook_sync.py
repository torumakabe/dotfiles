"""Verify the two gitleaks hook scripts keep an identical scanner block.

ADR-020 deliberately keeps two copies of the gitleaks launcher: the
config-based hook (~/.local/bin/gitleaks-pre-commit) and the
init.templateDir hook (~/.config/git/templates/hooks/pre-commit).
Sharing one file would couple their lifecycles, so ADR-020 chose
duplication and asks for both to be updated together. This test enforces
that rule instead of relying on the author remembering it.
"""
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_HOOK = REPO_ROOT / "home/dot_local/bin/executable_gitleaks-pre-commit"
TEMPLATE_HOOK = REPO_ROOT / "home/dot_config/git/templates/hooks/executable_pre-commit"

_SHARED_MARKER = "find_gitleaks() {"


def _find_bash() -> str | None:
    if os.name == "nt":
        program_files = os.environ.get("ProgramFiles")
        if not program_files:
            return None
        bash = pathlib.Path(program_files) / "Git/bin/bash.exe"
        return str(bash) if bash.is_file() else None
    return shutil.which("bash")


def _shell_path(path: pathlib.Path) -> str:
    value = path.as_posix()
    if os.name == "nt" and path.drive:
        return f"/{path.drive[0].lower()}{value[len(path.drive):]}"
    return value


BASH = _find_bash()


def _shared_block(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8")
    index = text.find(_SHARED_MARKER)
    if index < 0:
        raise AssertionError(f"{path} no longer contains {_SHARED_MARKER!r}")
    return text[index:]


def _write_scanner(path: pathlib.Path, label: str, exit_code: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        f"printf '%s:%s\\n' '{label}' \"$*\" >> \"$GITLEAKS_TEST_LOG\"\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
        newline="\n",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class GitleaksHookSyncTests(unittest.TestCase):
    def test_scanner_fixture_uses_lf_on_every_platform(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner = pathlib.Path(temporary) / "gitleaks.exe"
            _write_scanner(scanner, "fixture")
            contents = scanner.read_bytes()
            self.assertTrue(contents.startswith(b"#!/bin/sh\n"))
            self.assertNotIn(b"\r", contents)

    def test_shared_block_identical(self) -> None:
        self.assertEqual(_shared_block(CONFIG_HOOK), _shared_block(TEMPLATE_HOOK))

    def test_both_stay_posix_sh(self) -> None:
        for path in (CONFIG_HOOK, TEMPLATE_HOOK):
            with self.subTest(path=path.name):
                first_line = path.read_text(encoding="utf-8").splitlines()[0]
                self.assertEqual(first_line, "#!/bin/sh")

    def test_shared_block_has_no_mise_execution_or_install_guidance(self) -> None:
        block = _shared_block(CONFIG_HOOK)
        self.assertNotIn("mise install", block)
        self.assertIn("is_mise_shim_path", block)
        self.assertIn("/Microsoft/WinGet/Links/gitleaks.exe", block)
        self.assertIn("/opt/homebrew/opt/gitleaks/bin/gitleaks", block)
        self.assertIn("/usr/bin/cygpath", block)
        self.assertIn("Run chezmoi apply", block)


@unittest.skipUnless(BASH, "Git Bash is required on Windows; bash is required elsewhere")
class GitleaksHookExecutionTests(unittest.TestCase):
    def _run(
        self,
        home: pathlib.Path,
        path: list[pathlib.Path | str],
        *,
        local_app_data: pathlib.Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOME"] = _shell_path(home)
        env["PATH"] = ":".join(
            _shell_path(item) if isinstance(item, pathlib.Path) else item
            for item in path
        )
        env["GITLEAKS_TEST_LOG"] = _shell_path(home / "gitleaks.log")
        if local_app_data is None:
            env.pop("LOCALAPPDATA", None)
        else:
            env["LOCALAPPDATA"] = str(local_app_data)
        if os.name == "nt":
            env["MSYS_NO_PATHCONV"] = "1"
        return subprocess.run(
            [BASH, "--noprofile", "--norc", _shell_path(CONFIG_HOOK)],
            text=True,
            capture_output=True,
            encoding="utf-8",
            env=env,
            check=False,
        )

    def test_prefers_managed_local_binary_and_passes_exact_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary)
            name = "gitleaks.exe" if os.name == "nt" else "gitleaks"
            scanner = home / ".local/bin" / name
            _write_scanner(scanner, "local")
            result = self._run(home, ["/usr/bin", "/bin"])
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                "local:git --pre-commit --staged --redact --verbose --no-banner\n",
                (home / "gitleaks.log").read_text(encoding="utf-8"),
            )

    def test_skips_stale_mise_path_entry_and_uses_later_path_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary)
            name = "gitleaks.exe" if os.name == "nt" else "gitleaks"
            stale = home / ".local/share/mise/shims" / name
            fallback = home / "path-bin" / name
            _write_scanner(stale, "stale")
            _write_scanner(fallback, "path")
            result = self._run(
                home,
                [stale.parent, fallback.parent, "/usr/bin", "/bin"],
            )
            self.assertEqual(0, result.returncode, result.stderr)
            log = (home / "gitleaks.log").read_text(encoding="utf-8")
            self.assertTrue(log.startswith("path:"), log)
            self.assertNotIn("stale:", log)

    @unittest.skipIf(
        os.name == "nt",
        "POSIX symlink fixture; Windows stale-shim filtering has a static contract",
    )
    def test_rejects_managed_bin_symlink_to_stale_mise_shim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary)
            stale = home / ".local/share/mise/shims/gitleaks"
            target = home / ".local/bin/gitleaks"
            _write_scanner(stale, "stale")
            target.parent.mkdir(parents=True)
            target.symlink_to(stale)
            empty_path = home / "empty-path"
            empty_path.mkdir()
            result = self._run(home, [empty_path])
            self.assertEqual(0, result.returncode)
            self.assertIn("gitleaks not found", result.stderr)
            self.assertFalse((home / "gitleaks.log").exists())

    def test_uses_windows_winget_alias_when_stable_bin_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary)
            local_app_data = home / "LocalAppData"
            scanner = (
                local_app_data / "Microsoft/WinGet/Links/gitleaks.exe"
            )
            _write_scanner(scanner, "winget")
            result = self._run(
                home,
                ["/usr/bin", "/bin"],
                local_app_data=local_app_data,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(
                (home / "gitleaks.log").read_text(encoding="utf-8").startswith(
                    "winget:"
                )
            )

    def test_missing_scanner_warns_but_preserves_fail_open_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary)
            empty_path = home / "empty-path"
            empty_path.mkdir()
            result = self._run(home, [empty_path])
            self.assertEqual(0, result.returncode)
            self.assertIn("gitleaks not found", result.stderr)
            self.assertIn("Run chezmoi apply", result.stderr)

    def test_scanner_failure_blocks_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary)
            name = "gitleaks.exe" if os.name == "nt" else "gitleaks"
            scanner = home / ".local/bin" / name
            _write_scanner(scanner, "failure", exit_code=17)
            result = self._run(home, ["/usr/bin", "/bin"])
            self.assertEqual(17, result.returncode)


if __name__ == "__main__":
    unittest.main()
