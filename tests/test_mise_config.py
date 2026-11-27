"""Verify mise backend configuration and bootstrap behavior stay aligned."""

import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
GIT_ATTRIBUTES_PATH = REPO_ROOT / ".gitattributes"
CONFIG_PATH = REPO_ROOT / "home/dot_config/mise/config.toml.tmpl"
LOCK_PATH = REPO_ROOT / "home/dot_config/mise/private_mise.lock"
MISE_SOURCE_PATH = REPO_ROOT / "home/dot_config/mise"
SYNC_PS1_PATH = REPO_ROOT / "home/run_onchange_after_15-mise-sync-tools.ps1.tmpl"
BOOTSTRAP_SH_PATH = REPO_ROOT / "home/run_once_before_20-install-mise.sh.tmpl"
ZSHRC_PATH = REPO_ROOT / "home/dot_zshrc.tmpl"
POWERSHELL_PROFILE_PATH = REPO_ROOT / "home/PowerShell_profile.ps1.tmpl"

MISE_LOCK_PLATFORMS = (
    "linux-x64",
    "linux-arm64",
    "macos-arm64",
    "windows-x64",
    "windows-arm64",
)
CARGO_MAKE_EXCLUDED_PLATFORM = ("linux", "arm64")
EXACT_LOCKS_SOURCE_PATTERN = re.compile(
    r"(?:remove_)?(?:external_)?exact_(?:private_)?(?:readonly_)?locks"
)

ALLOWED_WARNING = (
    "mise WARN  newer example-tool release 0.145.0 ignored by "
    "minimum_release_age (24h); latest eligible release is 0.144.6"
)
RECOVERED_FALLBACK_WARNING = (
    "mise WARN  mise-versions endpoint=github_release repo=sigstore/cosign "
    "tag=v3.1.2 outcome=failed status=502 fallback=true "
    'error="HTTP status server error (502 Bad Gateway): Failed to fetch GitHub release"'
)
WARNING_CASES = (
    ("allowed-minimum-release-age", f"{ALLOWED_WARNING}\n", True),
    (
        "allowed-minimum-release-age-with-ansi",
        f"\x1b[33m{ALLOWED_WARNING}\x1b[0m\n",
        True,
    ),
    (
        "allowed-recovered-fallback",
        f"{RECOVERED_FALLBACK_WARNING}\n",
        True,
    ),
    (
        "fallback-false",
        f"{RECOVERED_FALLBACK_WARNING.replace('fallback=true', 'fallback=false')}\n",
        False,
    ),
    (
        "fallback-missing",
        "mise WARN  mise-versions endpoint=github_release repo=sigstore/cosign "
        "tag=v3.1.2 outcome=failed status=502\n",
        False,
    ),
    (
        "fallback-from-unknown-component",
        "mise WARN  plugin-cache endpoint=github_release repo=sigstore/cosign "
        "tag=v3.1.2 outcome=failed status=502 fallback=true\n",
        False,
    ),
    ("unknown", "mise WARN missing: uv@0.11.30\n", False),
    (
        "allowed-and-unknown",
        f"{ALLOWED_WARNING}\nmise WARN failed to verify tool metadata\n",
        False,
    ),
    (
        "extended-allowed-warning",
        f"{ALLOWED_WARNING}; checksum verification failed\n",
        False,
    ),
)


def _tool_alias(config: str, tool: str) -> str:
    match = re.search(
        rf"(?ms)^\[tool_alias\]\s*$.*?^{re.escape(tool)}\s*=\s*\"([^\"]+)\"\s*$",
        config,
    )
    if match is None:
        raise AssertionError(f"Missing [tool_alias] entry for {tool}")
    return match.group(1)


def _config_toml(config: str) -> dict:
    """chezmoi のテンプレート行を除いた config.toml.tmpl を TOML として読む。"""
    stripped = re.sub(r"(?m)^\{\{.*\}\}[ \t]*$\n?", "", config)
    return tomllib.loads(stripped)


def _lockfile_platforms(config: str) -> list[str]:
    settings = _config_toml(config).get("settings", {})
    if "lockfile_platforms" not in settings:
        raise AssertionError("[settings] に lockfile_platforms がありません")
    return settings["lockfile_platforms"]


def _mise_warning_helpers() -> str:
    zshrc = ZSHRC_PATH.read_text(encoding="utf-8")
    start = zshrc.index("_mise_normalize_log_line() {")
    end = zshrc.index("mise-upgrade() {")
    return zshrc[start:end]


class MiseConfigTests(unittest.TestCase):
    def test_mise_bootstrap_excludes_known_vulnerable_release(self) -> None:
        bootstrap_script = BOOTSTRAP_SH_PATH.read_text(encoding="utf-8")
        version_match = re.search(
            r'^MISE_VERSION="v(\d+)\.(\d+)\.(\d+)"$',
            bootstrap_script,
            re.MULTILINE,
        )

        self.assertIsNotNone(version_match)
        version = tuple(int(part) for part in version_match.groups())
        self.assertGreaterEqual(version, (2026, 7, 14), "GHSA-g74g-rg72-j2p3")

    def test_mise_bootstrap_renders_cleanly_for_unix_platforms(self) -> None:
        chezmoi = shutil.which("chezmoi")
        bash = shutil.which("bash")
        shellcheck = shutil.which("shellcheck")
        if chezmoi is None or bash is None or shellcheck is None:
            self.skipTest("chezmoi, bash, and shellcheck are required")

        for os_name, arch in (("darwin", "arm64"), ("linux", "amd64")):
            with self.subTest(os=os_name, arch=arch):
                rendered = subprocess.run(
                    [
                        chezmoi,
                        "execute-template",
                        "--override-data",
                        json.dumps({"chezmoi": {"os": os_name, "arch": arch}}),
                        "--file",
                        str(BOOTSTRAP_SH_PATH),
                    ],
                    check=False,
                    capture_output=True,
                    encoding="utf-8",
                )
                self.assertEqual(rendered.returncode, 0, rendered.stderr)
                rendered_script = (
                    rendered.stdout.replace("\r\n", "\n").replace("\r", "\n")
                ).encode("utf-8")

                syntax = subprocess.run(
                    [bash, "-n"],
                    input=rendered_script,
                    check=False,
                    capture_output=True,
                )
                self.assertEqual(
                    syntax.returncode,
                    0,
                    syntax.stderr.decode("utf-8", errors="replace"),
                )

                lint = subprocess.run(
                    [shellcheck, "-s", "bash", "-"],
                    input=rendered_script,
                    check=False,
                    capture_output=True,
                )
                self.assertEqual(
                    lint.returncode,
                    0,
                    (lint.stdout + lint.stderr).decode("utf-8", errors="replace"),
                )

    def test_dotnet_alias_matches_lock_backend(self) -> None:
        config = CONFIG_PATH.read_text(encoding="utf-8")
        lock = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))

        dotnet_entries = lock["tools"]["dotnet"]
        self.assertEqual(len(dotnet_entries), 1)
        self.assertEqual(_tool_alias(config, "dotnet"), dotnet_entries[0]["backend"])

    def test_lockfile_sidecars_are_complete_and_exact(self) -> None:
        chezmoi = shutil.which("chezmoi")
        if chezmoi is None:
            self.skipTest("chezmoi is required for sidecar source mapping tests")

        lock = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))
        referenced_sidecars: set[pathlib.PurePosixPath] = set()

        for tool_entries in lock["tools"].values():
            entries = tool_entries if isinstance(tool_entries, list) else [tool_entries]
            for entry in entries:
                aube = entry.get("aube")
                if aube is None:
                    continue
                relative_path = pathlib.PurePosixPath(aube["path"])
                self.assertFalse(relative_path.is_absolute())
                self.assertEqual(relative_path.parts[0], "locks")
                self.assertNotIn("..", relative_path.parts)
                referenced_sidecars.add(
                    pathlib.PurePosixPath(*relative_path.parts[1:])
                )

        source_roots = [
            path
            for path in MISE_SOURCE_PATH.iterdir()
            if path.is_dir()
            and EXACT_LOCKS_SOURCE_PATTERN.fullmatch(path.name)
        ]
        self.assertEqual(len(source_roots), 1)
        source_root = source_roots[0]
        nested_directories = [
            path for path in source_root.rglob("*") if path.is_dir()
        ]
        self.assertTrue(nested_directories)
        for directory in nested_directories:
            with self.subTest(directory=directory.relative_to(source_root)):
                self.assertTrue(directory.name.startswith("exact_"))
        package_files = [
            path for path in source_root.rglob("*") if path.name.endswith("package.json")
        ]
        aube_files = [
            path for path in source_root.rglob("*") if path.name.endswith("aube-lock.yaml")
        ]
        self.assertEqual(len(package_files), len(aube_files))

        with tempfile.TemporaryDirectory() as destination_dir:
            target_root = pathlib.Path(destination_dir) / ".config/mise/locks"
            chezmoi_args = [
                chezmoi,
                "--source",
                str(REPO_ROOT),
                "--destination",
                destination_dir,
            ]
            managed_sidecars: set[pathlib.PurePosixPath] = set()
            for source_file in package_files:
                target = subprocess.run(
                    chezmoi_args + ["target-path", str(source_file)],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                target_parent = pathlib.Path(target).parent
                managed_sidecars.add(
                    pathlib.PurePosixPath(
                        *target_parent.relative_to(target_root).parts
                    )
                )
                matching_aube = []
                for path in aube_files:
                    aube_target = subprocess.run(
                        chezmoi_args + ["target-path", str(path)],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip()
                    if aube_target and pathlib.Path(aube_target) == (
                        target_parent / "aube-lock.yaml"
                    ):
                        matching_aube.append(path)
                self.assertEqual(
                    len(matching_aube),
                    1,
                    f"missing aube-lock.yaml beside "
                    f"{target_parent / 'package.json'}",
                )

        self.assertEqual(managed_sidecars, referenced_sidecars)

    def test_mise_lock_artifacts_disable_git_text_conversion(self) -> None:
        git = shutil.which("git")
        if git is None:
            self.skipTest("git is required for attribute tests")

        self.assertTrue(GIT_ATTRIBUTES_PATH.is_file())
        artifact_paths = [LOCK_PATH.relative_to(REPO_ROOT).as_posix()]
        artifact_paths.extend(
            path.relative_to(REPO_ROOT).as_posix()
            for path in MISE_SOURCE_PATH.rglob("*")
            if path.is_file()
            and "locks" in path.relative_to(MISE_SOURCE_PATH).parts[0]
        )
        artifact_paths.append(
            "home/dot_config/mise/exact_private_locks/"
            "exact_example/exact_1/package.json"
        )
        self.assertGreater(len(artifact_paths), 1)
        for relative_path in artifact_paths:
            with self.subTest(path=relative_path):
                result = subprocess.run(
                    [git, "check-attr", "text", "--", relative_path],
                    cwd=REPO_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.stdout.strip(),
                    f"{relative_path}: text: unset",
                )

    def test_windows_lock_sync_persists_direct_bin_paths_without_shims(self) -> None:
        """撤去単位: Windows の direct mise bin PATH 同期。

        撤去条件は `.github/copilot-instructions.md` の「GitHub Copilot sandbox の
        Windows mise shim 回避」に従う。条件が整ったら、このテストと
        User PATH 同期、state file 管理をまとめて削除する。
        """
        powershell_script = SYNC_PS1_PATH.read_text(encoding="utf-8")

        self.assertIn("& $miseExe bin-paths", powershell_script)
        self.assertIn("[Microsoft.Win32.Registry]::CurrentUser", powershell_script)
        self.assertIn("$key.SetValue('Path'", powershell_script)
        self.assertIn("mise-windows-user-paths.txt", powershell_script)
        self.assertIn("mise\\shims", powershell_script)
        self.assertIn("$normalizedBinPaths", powershell_script)
        self.assertIn("DoNotExpandEnvironmentNames", powershell_script)
        self.assertIn("RegistryValueKind", powershell_script)
        self.assertIn("Publish-EnvironmentChange", powershell_script)
        self.assertIn("Test-MiseManagedPath", powershell_script)
        self.assertIn("30000 characters", powershell_script)
        self.assertFalse(
            (
                REPO_ROOT
                / "home/run_once_after_05-setup-mise-shims-path.ps1.tmpl"
            ).exists()
        )

    def _check_mise_warnings(self, log: str) -> subprocess.CompletedProcess[str]:
        if shutil.which("zsh") is None:
            self.skipTest("zsh is required for mise warning tests")

        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as log_file:
            log_file.write(log)
            log_file.flush()
            script = (
                _mise_warning_helpers()
                + '\n_mise_check_warnings "$1" "mise upgrade"\n'
            )
            return subprocess.run(
                ["zsh", "-c", script, "mise-warning-test", log_file.name],
                check=False,
                capture_output=True,
                text=True,
            )

    def test_zsh_mise_warning_cases(self) -> None:
        for name, log, allowed in WARNING_CASES:
            with self.subTest(name=name):
                result = self._check_mise_warnings(log)
                if allowed:
                    self.assertEqual(result.returncode, 0)
                    self.assertIn("処理を継続します", result.stderr)
                    if "recovered-fallback" in name:
                        self.assertIn("回復済み", result.stderr)
                    else:
                        self.assertIn("リリース待機期間", result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("処理を中止する警告", result.stderr)
                if name == "allowed-minimum-release-age-with-ansi":
                    self.assertNotIn("\x1b", result.stderr)

    def _run_zsh_sidecar_validation(
        self,
        lockfile: pathlib.Path,
        config_dir: pathlib.Path,
    ) -> subprocess.CompletedProcess[str]:
        if shutil.which("zsh") is None:
            self.skipTest("zsh is required for mise sidecar validation tests")

        script = (
            _mise_warning_helpers()
            + '\n_mise_validate_lock_sidecars "$1" "$2"\n'
        )
        return subprocess.run(
            [
                "zsh",
                "-c",
                script,
                "mise-sidecar-validation-test",
                str(lockfile),
                str(config_dir),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_zsh_rejects_unsafe_sidecar_paths(self) -> None:
        for aube_path in (r"locks/example\evil/1", "locks/../evil"):
            with self.subTest(aube_path=aube_path):
                with tempfile.TemporaryDirectory() as temp_dir:
                    config_dir = pathlib.Path(temp_dir)
                    lockfile = config_dir / "mise.lock"
                    lockfile.write_text(
                        f'aube = {{ path = "{aube_path}", '
                        'digest = "sha256:test" }\n',
                        encoding="utf-8",
                    )

                    result = self._run_zsh_sidecar_validation(
                        lockfile, config_dir
                    )

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        "dependency sidecar path が不正です",
                        result.stderr,
                    )

    def test_mise_lock_platform_contract_stays_aligned(self) -> None:
        config = CONFIG_PATH.read_text(encoding="utf-8")
        zshrc = ZSHRC_PATH.read_text(encoding="utf-8")
        profile = POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8")

        platforms = _lockfile_platforms(config)
        platform_csv = ",".join(platforms)
        self.assertEqual(platforms, list(MISE_LOCK_PLATFORMS))
        self.assertIn(
            f"mise lock --global --platform {platform_csv} --bump",
            zshrc,
        )
        self.assertIn(
            f'-Arguments @("lock", "--global", "--platform", "{platform_csv}", "--bump")',
            profile,
        )

    def test_mise_shims_are_disabled_only_in_windows_config(self) -> None:
        chezmoi = shutil.which("chezmoi")
        if chezmoi is None:
            self.skipTest("chezmoi is required to render the platform config")

        rendered_settings: dict[str, dict] = {}
        for os_name in ("windows", "darwin"):
            with self.subTest(os=os_name):
                rendered = subprocess.run(
                    [
                        chezmoi,
                        "execute-template",
                        "--override-data",
                        json.dumps(
                            {"chezmoi": {"os": os_name, "arch": "arm64"}}
                        ),
                        "--file",
                        str(CONFIG_PATH),
                    ],
                    check=False,
                    capture_output=True,
                    encoding="utf-8",
                )
                self.assertEqual(rendered.returncode, 0, rendered.stderr)
                rendered_settings[os_name] = tomllib.loads(rendered.stdout).get(
                    "settings", {}
                )

        self.assertIs(rendered_settings["windows"].get("activate_shims"), False)
        self.assertNotIn("activate_shims", rendered_settings["darwin"])

    def test_cargo_make_linux_arm64_constraint_stays_aligned(self) -> None:
        config = CONFIG_PATH.read_text(encoding="utf-8")

        cargo_make_block = re.search(
            r'{{ if not \(and \(eq \.chezmoi\.os "([^"]+)"\) '
            r'\(eq \.chezmoi\.arch "([^"]+)"\)\) -}}\s*'
            r"# [^\n]*\s*cargo-make = \"latest\"\s*{{ end -}}",
            config,
        )
        self.assertIsNotNone(cargo_make_block)
        self.assertEqual(cargo_make_block.groups(), CARGO_MAKE_EXCLUDED_PLATFORM)

if __name__ == "__main__":
    unittest.main()
