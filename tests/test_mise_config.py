"""Verify mise backend configuration and migration instructions stay aligned."""

import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "home/dot_config/mise/config.toml.tmpl"
LOCK_PATH = REPO_ROOT / "home/dot_config/mise/private_mise.lock"
INSTRUCTIONS_PATH = REPO_ROOT / ".github/copilot-instructions.md"
SYNC_SH_PATH = REPO_ROOT / "home/run_onchange_after_15-mise-sync-tools.sh.tmpl"
SYNC_PS1_PATH = REPO_ROOT / "home/run_onchange_after_15-mise-sync-tools.ps1.tmpl"
INSTALL_SH_PATH = REPO_ROOT / "home/run_once_after_20-mise-install.sh.tmpl"
BOOTSTRAP_SH_PATH = REPO_ROOT / "home/run_once_before_20-install-mise.sh.tmpl"
ZSHRC_PATH = REPO_ROOT / "home/dot_zshrc.tmpl"
POWERSHELL_PROFILE_PATH = REPO_ROOT / "home/PowerShell_profile.ps1.tmpl"
OPERATIONS_PATH = REPO_ROOT / "docs/operations.md"
TROUBLESHOOTING_PATH = REPO_ROOT / "docs/troubleshooting.md"

MISE_LOCK_PLATFORMS = (
    "linux-x64",
    "linux-arm64",
    "macos-arm64",
    "windows-x64",
    "windows-arm64",
)
MISE_LOCK_PLATFORM_CSV = ",".join(MISE_LOCK_PLATFORMS)
CARGO_MAKE_EXCLUDED_PLATFORM = ("linux", "arm64")
CARGO_MAKE_UPSTREAM_ISSUE = "https://github.com/sagiegurari/cargo-make/issues/541"

# aube の trustPolicy=no-downgrade 除外。プロキシが証跡を落とす版だけを明記し、
# パッケージ名だけの除外へ広げない（将来版の検査を残すため）。
TRUST_POLICY_EXCLUDES = {
    "npm:typescript-language-server": (
        "typescript-language-server@5.3.0",
        "typescript-language-server@>=6 <7",
    ),
}
LSP_TYPESCRIPT_VERSION = "6.0.3"
LSP_CONFIG_PATH = REPO_ROOT / "home/private_dot_copilot/lsp-config.json.tmpl"
LSP_VERSION_PATH = REPO_ROOT / "home/.chezmoidata.toml"
LSP_INSTALL_SH_PATH = (
    REPO_ROOT / "home/run_after_22-install-typescript-lsp.sh.tmpl"
)
LSP_INSTALL_PS1_PATH = (
    REPO_ROOT / "home/run_after_22-install-typescript-lsp.ps1.tmpl"
)

ALLOWED_WARNING = (
    "mise WARN  newer codex release 0.145.0 ignored by "
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


def _powershell_mise_upgrade_function() -> str:
    profile = POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8")
    start = profile.index("function Invoke-MiseUpgrade {")
    next_function = re.search(r"(?m)^function \S+", profile[start + 1 :])
    if next_function is None:
        raise AssertionError("Invoke-MiseUpgrade の次のトップレベル関数がありません")
    return profile[start : start + 1 + next_function.start()]


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
        self.assertEqual(
            len(re.findall(r'expected_sha256="[0-9a-f]{64}"', bootstrap_script)),
            3,
        )

    def test_mise_bootstrap_uses_official_release_archives(self) -> None:
        bootstrap_script = BOOTSTRAP_SH_PATH.read_text(encoding="utf-8")

        self.assertIn(
            'archive_url="https://github.com/jdx/mise/releases/download/'
            '${MISE_VERSION}/${mise_archive}"',
            bootstrap_script,
        )
        archives = {
            "macos-arm64.tar.gz": (
                "ac6ed53215e70abfb220524aed121bf02"
                "dbd3fbd4a19355032dd1c5a108fb212"
            ),
            "linux-x64.tar.gz": (
                "e013fe11a0a9055fe78d2546baa85eba"
                "90a56e6445c431021b4fe328e6910fe2"
            ),
            "linux-arm64.tar.gz": (
                "5fd8a9ffb312b47e29f642d377ad4fa"
                "9093962b47061ef5c15665086904e1046"
            ),
        }
        for archive, checksum in archives.items():
            archive_index = bootstrap_script.index(archive)
            checksum_index = bootstrap_script.index(checksum)
            self.assertLess(archive_index, checksum_index)
        self.assertNotIn("brew install mise", bootstrap_script)

    def test_mise_bootstrap_migrates_homebrew_after_verification(self) -> None:
        bootstrap_script = BOOTSTRAP_SH_PATH.read_text(encoding="utf-8")

        self.assertIn("brew list --formula mise", bootstrap_script)
        self.assertIn(
            '[ -n "${mise_path}" ] && [ "${homebrew_mise}" -eq 0 ]',
            bootstrap_script,
        )
        checksum_index = bootstrap_script.index(
            'if [ "${actual_sha256}" != "${expected_sha256}" ]'
        )
        install_index = bootstrap_script.index(
            'install -m 0755 "${tmp_dir}/mise/bin/mise" "${staged_path}"'
        )
        verify_index = bootstrap_script.index(
            '"${staged_path}" --version'
        )
        move_index = bootstrap_script.index(
            'mv -f "${staged_path}" "${MISE_BIN_DIR}/mise"'
        )
        cleanup_index = bootstrap_script.index(
            "report_homebrew_mise_cleanup", move_index
        )
        self.assertLess(checksum_index, install_index)
        self.assertLess(install_index, verify_index)
        self.assertLess(verify_index, move_index)
        self.assertLess(move_index, cleanup_index)

    def test_mise_bootstrap_verifies_binary_with_mise_basename(self) -> None:
        bootstrap_script = BOOTSTRAP_SH_PATH.read_text(encoding="utf-8")

        self.assertIn(
            'staged_dir="$(mktemp -d "${MISE_BIN_DIR}/.mise.XXXXXX")"',
            bootstrap_script,
        )
        self.assertIn('staged_path="${staged_dir}/mise"', bootstrap_script)
        self.assertNotIn(
            'staged_path="$(mktemp "${MISE_BIN_DIR}/.mise.XXXXXX")"',
            bootstrap_script,
        )

    def test_mise_bootstrap_preserves_non_homebrew_installations(self) -> None:
        bootstrap_script = BOOTSTRAP_SH_PATH.read_text(encoding="utf-8")

        formula_detection = bootstrap_script[
            bootstrap_script.index("brew list --formula mise") :
            bootstrap_script.index("download_file() {")
        ]
        self.assertIn(
            '[ "${mise_path}" -ef "${brew_mise_link}" ]',
            formula_detection,
        )
        self.assertIn(
            '[ "${mise_path}" -ef "${brew_mise_bin}" ]',
            formula_detection,
        )
        self.assertIn(
            'if ! existing_version="$("${mise_path}" --version)"; then',
            formula_detection,
        )
        self.assertIn(
            'if [ -e "${MISE_BIN_DIR}/mise" ] '
            '|| [ -L "${MISE_BIN_DIR}/mise" ]; then',
            formula_detection,
        )
        self.assertLess(
            formula_detection.index(
                'if ! existing_version="$("${mise_path}" --version)"; then'
            ),
            formula_detection.index("report_homebrew_mise_cleanup"),
        )

    def test_mise_bootstrap_defers_homebrew_cleanup_until_new_shell(self) -> None:
        bootstrap_script = BOOTSTRAP_SH_PATH.read_text(encoding="utf-8")
        operations = OPERATIONS_PATH.read_text(encoding="utf-8")
        troubleshooting = TROUBLESHOOTING_PATH.read_text(encoding="utf-8")
        cleanup_function = bootstrap_script[
            bootstrap_script.index("report_homebrew_mise_cleanup() {") :
            bootstrap_script.index("{{ if eq .chezmoi.os")
        ]
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is required")

        expected_mise = "/custom/bin/mise"
        result = subprocess.run(
            [bash],
            input=(
                "set -euo pipefail\n"
                f"{cleanup_function}\n"
                f'report_homebrew_mise_cleanup "{expected_mise}"\n'
            ),
            check=False,
            capture_output=True,
            encoding="utf-8",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("current shell activation", result.stderr)
        self.assertIn("Restart every shell", result.stderr)
        self.assertIn("command -v mise", result.stderr)
        self.assertIn(expected_mise, result.stderr)
        self.assertIn("brew uninstall mise", result.stderr)
        uninstall_lines = [
            line.strip()
            for line in bootstrap_script.splitlines()
            if "brew uninstall mise" in line
        ]
        self.assertEqual(
            uninstall_lines,
            ['echo "then run \'brew uninstall mise\' manually." >&2'],
        )
        self.assertIn("導入スクリプトは formula を削除しない", operations)
        self.assertIn("PATH 外の任意の場所は探索しない", operations)
        self.assertIn("_mise_hook: no such file or directory", troubleshooting)
        self.assertIn("unset __DOTFILES_PROFILE_LOADED", troubleshooting)
        self.assertIn(
            'mise_path="$HOME/.local/bin/mise"',
            troubleshooting,
        )
        self.assertIn(
            'eval "$("$mise_path" activate zsh)"',
            troubleshooting,
        )

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

                syntax = subprocess.run(
                    [bash, "-n"],
                    input=rendered.stdout,
                    check=False,
                    capture_output=True,
                    encoding="utf-8",
                )
                self.assertEqual(syntax.returncode, 0, syntax.stderr)

                lint = subprocess.run(
                    [shellcheck, "-s", "bash", "-"],
                    input=rendered.stdout,
                    check=False,
                    capture_output=True,
                    encoding="utf-8",
                )
                self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)

    def test_mise_homebrew_migration_has_removal_condition(self) -> None:
        instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")

        self.assertIn("Homebrew formula 版 mise の移行案内 (ADR-027)", instructions)
        self.assertIn("brew list --formula mise", instructions)
        self.assertIn("activation hook", instructions)
        self.assertIn(
            "Homebrew の検出、既存バイナリとの調停、移行案内と関連テスト"
            "を撤去する",
            instructions,
        )
        self.assertIn("公式バイナリの導入処理は残す", instructions)

    def test_mise_install_does_not_retry_without_github_credentials(self) -> None:
        install_script = INSTALL_SH_PATH.read_text(encoding="utf-8")

        self.assertNotIn("retry_missing_tools_without_github_credentials", install_script)
        self.assertNotIn(
            "unset GITHUB_TOKEN GH_TOKEN MISE_GITHUB_TOKEN",
            install_script,
        )

    def test_dotnet_alias_matches_lock_backend(self) -> None:
        config = CONFIG_PATH.read_text(encoding="utf-8")
        lock = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))

        dotnet_entries = lock["tools"]["dotnet"]
        self.assertEqual(len(dotnet_entries), 1)
        self.assertEqual(_tool_alias(config, "dotnet"), dotnet_entries[0]["backend"])

    def test_windows_dotnet_verification_uses_mise_root(self) -> None:
        config = CONFIG_PATH.read_text(encoding="utf-8")

        self.assertIn('[tools.dotnet]\nversion = "latest"', config)
        self.assertIn('{{ if eq .chezmoi.os "windows" -}}', config)
        self.assertIn("install_env = { DOTNET_ROOT =", config)
        self.assertIn(r"\mise\dotnet-root;$PATH", config)

    def test_typescript_language_server_uses_stable_typescript_path(self) -> None:
        config = CONFIG_PATH.read_text(encoding="utf-8")
        tools = _config_toml(config)["tools"]
        language_server = tools["npm:typescript-language-server"]

        self.assertEqual(tools["npm:typescript"], "latest")
        self.assertNotIn("postinstall", language_server)
        self.assertEqual(
            tomllib.loads(LSP_VERSION_PATH.read_text(encoding="utf-8"))[
                "typescriptLsp"
            ]["version"],
            LSP_TYPESCRIPT_VERSION,
        )

        chezmoi = shutil.which("chezmoi")
        if chezmoi is None:
            self.skipTest("chezmoi is required for LSP template tests")
        rendered_lsp = subprocess.run(
            [
                chezmoi,
                "execute-template",
                "--init",
                "--stdinisatty=false",
                "--file",
                str(LSP_CONFIG_PATH),
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        lsp_typescript = json.loads(rendered_lsp.stdout)["lspServers"]["typescript"]
        self.assertTrue(
            lsp_typescript["initializationOptions"]["tsserver"]["path"].endswith(
                "typescript-lsp\\node_modules\\typescript\\lib\\tsserver.js"
                if os.name == "nt"
                else "typescript-lsp/node_modules/typescript/lib/tsserver.js"
            )
        )

        source_root = REPO_ROOT / "home"
        rendered_ps1 = subprocess.run(
            [
                chezmoi,
                "--source",
                str(source_root),
                "execute-template",
                "--stdinisatty=false",
                "--override-data",
                json.dumps(
                    {
                        "chezmoi": {"os": "windows", "arch": "amd64"},
                        "typescriptLsp": {"version": LSP_TYPESCRIPT_VERSION},
                    }
                ),
                "--file",
                str(LSP_INSTALL_PS1_PATH),
            ],
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        rendered_sh = subprocess.run(
            [
                chezmoi,
                "--source",
                str(source_root),
                "execute-template",
                "--stdinisatty=false",
                "--override-data",
                json.dumps(
                    {
                        "chezmoi": {"os": "linux", "arch": "amd64"},
                        "typescriptLsp": {"version": LSP_TYPESCRIPT_VERSION},
                    }
                ),
                "--file",
                str(LSP_INSTALL_SH_PATH),
            ],
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        for rendered_script in (rendered_ps1, rendered_sh):
            with self.subTest(script=rendered_script[:30]):
                self.assertIn(LSP_TYPESCRIPT_VERSION, rendered_script)
                self.assertIn("typescript-lsp", rendered_script)
                self.assertIn("node_modules", rendered_script)
                self.assertIn("tsserver.js", rendered_script)
                self.assertIn("--prefix", rendered_script)
                self.assertIn("--no-save", rendered_script)
                self.assertIn("--package-lock=false", rendered_script)
                self.assertNotIn("install --global", rendered_script)

    def test_backend_migration_requires_postconditions(self) -> None:
        instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")

        for command in ("mise ls <tool>", "mise which <tool>", "<tool> --version"):
            with self.subTest(command=command):
                self.assertIn(command, instructions)
        self.assertIn("`missing` を表示しない", instructions)
        self.assertIn("backend 固有の install path", instructions)

    def test_lock_sync_propagates_mise_failure(self) -> None:
        shell_script = SYNC_SH_PATH.read_text(encoding="utf-8")
        powershell_script = SYNC_PS1_PATH.read_text(encoding="utf-8")

        self.assertIn('exit "$sync_exit"', shell_script)
        self.assertIn("exit $syncExit", powershell_script)
        for script in (shell_script, powershell_script):
            self.assertIn("chezmoi apply", script)
            self.assertNotIn("chezmoi apply --force", script)
            self.assertNotIn("次回 chezmoi apply 時に再試行", script)

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

    def test_mise_upgrade_backs_up_lockfile_before_upgrade(self) -> None:
        zshrc = ZSHRC_PATH.read_text(encoding="utf-8")
        function = zshrc[zshrc.index("mise-upgrade() {") :]

        self.assertLess(
            function.index('command cp -p "$lockfile" "$lock_backup"'),
            function.index('GITHUB_TOKEN="$token" mise upgrade'),
        )
        self.assertIn("emulate -L zsh", function)
        self.assertNotIn("grep -q 'mise WARN'", function)

    def test_mise_upgrade_helpers_use_local_zsh_options(self) -> None:
        helpers = _mise_warning_helpers()

        self.assertEqual(helpers.count("emulate -L zsh"), 4)

    def test_mise_upgrade_centralizes_lockfile_restore_reporting(self) -> None:
        zshrc = ZSHRC_PATH.read_text(encoding="utf-8")
        function = zshrc[zshrc.index("mise-upgrade() {") :]

        self.assertEqual(
            function.count(
                '_mise_restore_lockfile "$lockfile" "$lock_backup" "$had_lockfile"'
            ),
            4,
        )
        self.assertEqual(
            zshrc.count("mise upgrade 実行前の lockfile を復元しました"),
            1,
        )
        self.assertEqual(
            zshrc.count("mise upgrade 実行前の lockfile を復元できませんでした"),
            1,
        )

    def _run_zsh_lockfile_restore(
        self,
        lockfile: pathlib.Path,
        backup: pathlib.Path,
        had_lockfile: bool,
    ) -> subprocess.CompletedProcess[str]:
        if shutil.which("zsh") is None:
            self.skipTest("zsh is required for mise lockfile restore tests")

        script = (
            _mise_warning_helpers()
            + '\n_mise_restore_lockfile "$1" "$2" "$3"\n'
        )
        return subprocess.run(
            [
                "zsh",
                "-c",
                script,
                "mise-lockfile-restore-test",
                str(lockfile),
                str(backup),
                "1" if had_lockfile else "0",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_zsh_restores_existing_lockfile_from_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            lockfile = root / "mise.lock"
            backup = root / "mise.lock.backup"
            lockfile.write_text("generated", encoding="utf-8")
            backup.write_text("original", encoding="utf-8")

            result = self._run_zsh_lockfile_restore(lockfile, backup, True)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(lockfile.read_text(encoding="utf-8"), "original")
            self.assertFalse(backup.exists())
            self.assertIn("lockfile を復元しました", result.stderr)

    def test_zsh_removes_generated_lockfile_when_none_existed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            lockfile = root / "mise.lock"
            backup = root / "mise.lock.backup"
            lockfile.write_text("generated", encoding="utf-8")

            result = self._run_zsh_lockfile_restore(lockfile, backup, False)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(lockfile.exists())
            self.assertIn("lockfile を復元しました", result.stderr)

    def test_powershell_mise_upgrade_backs_up_before_upgrade(self) -> None:
        profile = POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8")
        function = profile[profile.index("function Invoke-MiseUpgrade {") :]

        self.assertLess(
            function.index("Copy-Item -Path $lockfile -Destination $lockBackup -Force"),
            function.index('-Arguments @("upgrade")'),
        )
        self.assertIn("[System.IO.Path]::GetTempFileName()", function)
        self.assertIn("Tee-Object -FilePath $miseLog -Append", function)
        self.assertIn("$capturedOutput = @(", function)

    def test_powershell_mise_upgrade_restores_lockfile_on_failure(self) -> None:
        profile = POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8")
        function = profile[profile.index("function Invoke-MiseUpgrade {") :]

        self.assertIn("function Restore-MiseLockfile {", function)
        self.assertIn("if ($restoreLockfileOnFailure)", function)
        self.assertIn("Restore-MiseLockfile", function)
        self.assertIn("throw $failure", function)

    def _run_powershell_mise_upgrade(
        self,
        *,
        upgrade_output: str = "",
        lock_output: str = "",
        upgrade_exit: int = 0,
        lock_exit: int = 0,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is required for PowerShell mise-upgrade tests")

        with tempfile.TemporaryDirectory() as temp_dir:
            test_root = pathlib.Path(temp_dir)
            lockfile = test_root / ".config/mise/mise.lock"
            lockfile.parent.mkdir(parents=True)
            lockfile.write_text("original-lock", encoding="utf-8")
            history_file = test_root / "history.txt"
            script_file = test_root / "test-mise-upgrade.ps1"
            script_file.write_text(
                f"""
$PSStyle.OutputRendering = 'PlainText'
$historyPath = $env:TEST_HISTORY
$testLockfile = Join-Path $HOME ".config\\mise\\mise.lock"

function Add-TestHistory {{
    param([string]$Entry)
    Add-Content -Path $historyPath -Value $Entry -Encoding utf8
}}

function gh {{
    Add-TestHistory "gh $($args -join ' ')"
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'auth' -and $args[1] -eq 'token') {{
        'test-token'
    }}
}}

function mise {{
    Add-TestHistory "mise $($args -join ' ')"
    if ($args[0] -eq 'upgrade') {{
        [System.IO.File]::WriteAllText($testLockfile, 'upgrade-lock')
        if ($env:TEST_UPGRADE_OUTPUT) {{
            $env:TEST_UPGRADE_OUTPUT
        }}
        $global:LASTEXITCODE = [int]$env:TEST_UPGRADE_EXIT
        return
    }}
    if ($args[0] -eq 'lock') {{
        [System.IO.File]::WriteAllText($testLockfile, 'new-lock')
        if ($env:TEST_LOCK_OUTPUT) {{
            $env:TEST_LOCK_OUTPUT
        }}
        $global:LASTEXITCODE = [int]$env:TEST_LOCK_EXIT
    }}
}}

function chezmoi {{
    Add-TestHistory "chezmoi $($args -join ' ')"
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'source-path') {{
        Join-Path $HOME 'source'
    }}
}}

function git {{
    Add-TestHistory "git $($args -join ' ')"
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'rev-parse') {{
        'main'
    }}
}}

{_powershell_mise_upgrade_function()}

$caught = $false
try {{
    Invoke-MiseUpgrade
}}
catch {{
    $caught = $true
}}

$result = @{{
    caught = $caught
    lock = [System.IO.File]::ReadAllText($testLockfile)
    history = @(
        if (Test-Path $historyPath) {{
            Get-Content -Path $historyPath
        }}
    )
}}
"RESULT_JSON=$($result | ConvertTo-Json -Compress)"
""",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update(
                {
                    "HOME": temp_dir,
                    "USERPROFILE": temp_dir,
                    "TEMP": temp_dir,
                    "TMP": temp_dir,
                    "TMPDIR": temp_dir,
                    "TEST_HISTORY": str(history_file),
                    "TEST_UPGRADE_OUTPUT": upgrade_output,
                    "TEST_LOCK_OUTPUT": lock_output,
                    "TEST_UPGRADE_EXIT": str(upgrade_exit),
                    "TEST_LOCK_EXIT": str(lock_exit),
                }
            )
            result = subprocess.run(
                [pwsh, "-NoProfile", "-NonInteractive", "-File", str(script_file)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
            )
            match = re.search(r"(?m)^RESULT_JSON=(.+)$", result.stdout)
            self.assertIsNotNone(
                match,
                f"PowerShell result marker missing\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )
            state = json.loads(match.group(1))

            output = result.stdout + result.stderr
            log_match = re.search(
                r"実行ログ:[\s|]*([^\r\n]+?\.tmp)\b",
                output,
            )
            if log_match:
                log_path = pathlib.Path(log_match.group(1).strip())
                state["log_path"] = str(log_path)
                state["log_exists"] = log_path.exists()
                log_path.unlink(missing_ok=True)

            return result, state

    def test_powershell_mise_warning_cases(self) -> None:
        for name, log, allowed in WARNING_CASES:
            with self.subTest(name=name):
                result, state = self._run_powershell_mise_upgrade(
                    upgrade_output=log.rstrip("\n")
                )

                self.assertEqual(result.returncode, 0)
                self.assertEqual(state["caught"], not allowed)
                self.assertEqual(
                    state["lock"],
                    "new-lock" if allowed else "original-lock",
                )
                if allowed:
                    self.assertIn("処理を継続します", result.stdout + result.stderr)
                    if "recovered-fallback" in name:
                        self.assertIn("回復済み", result.stdout + result.stderr)
                    else:
                        self.assertIn(
                            "リリース待機期間", result.stdout + result.stderr
                        )
                    self.assertTrue(
                        any(
                            item.startswith("mise lock --global --platform")
                            for item in state["history"]
                        )
                    )
                else:
                    self.assertEqual(state["history"], ["gh auth token", "mise upgrade"])
                    self.assertTrue(state["log_exists"])
                    self.assertIn(state["log_path"], result.stdout + result.stderr)

    def test_powershell_mise_lock_allows_recovered_fallback_warning(self) -> None:
        result, state = self._run_powershell_mise_upgrade(
            lock_output=RECOVERED_FALLBACK_WARNING
        )

        self.assertEqual(result.returncode, 0)
        self.assertFalse(state["caught"])
        self.assertEqual(state["lock"], "new-lock")
        self.assertIn("回復済み", result.stdout + result.stderr)
        self.assertTrue(
            any(item.startswith("chezmoi re-add") for item in state["history"])
        )
        self.assertIn("git add -A", state["history"])

    def test_powershell_mise_lock_restores_on_blocking_warning(self) -> None:
        result, state = self._run_powershell_mise_upgrade(
            lock_output="mise WARN failed to verify tool metadata"
        )

        self.assertEqual(result.returncode, 0)
        self.assertTrue(state["caught"])
        self.assertEqual(state["lock"], "original-lock")
        self.assertEqual(
            state["history"],
            [
                "gh auth token",
                "mise upgrade",
                f"mise lock --global --platform {MISE_LOCK_PLATFORM_CSV}",
            ],
        )
        self.assertTrue(state["log_exists"])

    def test_powershell_mise_upgrade_restores_on_upgrade_failure(self) -> None:
        result, state = self._run_powershell_mise_upgrade(upgrade_exit=23)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(state["caught"])
        self.assertEqual(state["lock"], "original-lock")
        self.assertEqual(state["history"], ["gh auth token", "mise upgrade"])
        self.assertTrue(state["log_exists"])

    def test_powershell_mise_upgrade_restores_on_lock_failure(self) -> None:
        result, state = self._run_powershell_mise_upgrade(lock_exit=29)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(state["caught"])
        self.assertEqual(state["lock"], "original-lock")
        self.assertEqual(
            state["history"],
            [
                "gh auth token",
                "mise upgrade",
                f"mise lock --global --platform {MISE_LOCK_PLATFORM_CSV}",
            ],
        )
        self.assertTrue(state["log_exists"])
        self.assertIn(
            "lockfile の再生成に失敗しました。実行ログを確認してください。",
            result.stdout + result.stderr,
        )
        self.assertNotIn("GITHUB_TOKEN の有効期限", result.stdout + result.stderr)

    def test_mise_lock_platform_contract_stays_aligned(self) -> None:
        config = CONFIG_PATH.read_text(encoding="utf-8")
        zshrc = ZSHRC_PATH.read_text(encoding="utf-8")
        profile = POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8")
        operations = OPERATIONS_PATH.read_text(encoding="utf-8")
        troubleshooting = TROUBLESHOOTING_PATH.read_text(encoding="utf-8")

        # config.toml が正本。CLI と文書はここから導出した値と突き合わせる。
        platforms = _lockfile_platforms(config)
        platform_csv = ",".join(platforms)
        self.assertEqual(platforms, list(MISE_LOCK_PLATFORMS))
        self.assertIn(
            f"lockfile_platforms = {json.dumps(platforms)}",
            operations,
        )
        self.assertIn(
            f"mise lock --global --platform {platform_csv}",
            zshrc,
        )
        self.assertIn(
            f'-Arguments @("lock", "--global", "--platform", "{platform_csv}")',
            profile,
        )
        for path, document in (
            (OPERATIONS_PATH, operations),
            (TROUBLESHOOTING_PATH, troubleshooting),
        ):
            with self.subTest(path=path):
                platform_values = re.findall(
                    r"mise lock --global --platform ([a-z0-9,-]+)",
                    document,
                )
                self.assertEqual(
                    set(platform_values),
                    {platform_csv},
                )

    def test_cargo_make_linux_arm64_constraint_stays_aligned(self) -> None:
        config = CONFIG_PATH.read_text(encoding="utf-8")
        instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")
        operations = OPERATIONS_PATH.read_text(encoding="utf-8")
        os_name, arch = CARGO_MAKE_EXCLUDED_PLATFORM
        platform = f"{os_name}/{arch}"

        cargo_make_block = re.search(
            r'{{ if not \(and \(eq \.chezmoi\.os "([^"]+)"\) '
            r'\(eq \.chezmoi\.arch "([^"]+)"\)\) -}}\s*'
            r"# [^\n]*\s*cargo-make = \"latest\"\s*{{ end -}}",
            config,
        )
        self.assertIsNotNone(cargo_make_block)
        self.assertEqual(cargo_make_block.groups(), CARGO_MAKE_EXCLUDED_PLATFORM)

        for path, document in (
            (INSTRUCTIONS_PATH, instructions),
            (OPERATIONS_PATH, operations),
        ):
            with self.subTest(path=path):
                cargo_make_lines = [
                    line for line in document.splitlines() if "cargo-make" in line
                ]
                self.assertTrue(cargo_make_lines)
                self.assertTrue(
                    all(platform in line for line in cargo_make_lines)
                )

        self.assertIn(CARGO_MAKE_UPSTREAM_ISSUE, instructions)

    def test_trust_policy_excludes_stay_version_scoped(self) -> None:
        config = CONFIG_PATH.read_text(encoding="utf-8")
        instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")
        operations = OPERATIONS_PATH.read_text(encoding="utf-8")
        troubleshooting = TROUBLESHOOTING_PATH.read_text(encoding="utf-8")
        tools = _config_toml(config)["tools"]

        configured = {
            name: tuple(spec["trust_policy_excludes"])
            for name, spec in tools.items()
            if isinstance(spec, dict) and "trust_policy_excludes" in spec
        }
        self.assertEqual(configured, TRUST_POLICY_EXCLUDES)

        for name, patterns in configured.items():
            with self.subTest(tool=name):
                # パッケージ名だけの除外は将来版の downgrade 検査も無効化する。
                for pattern in patterns:
                    self.assertIn("@", pattern)
                for path, document in (
                    (INSTRUCTIONS_PATH, instructions),
                    (OPERATIONS_PATH, operations),
                    (TROUBLESHOOTING_PATH, troubleshooting),
                ):
                    with self.subTest(path=path):
                        self.assertIn("trust_policy_excludes", document)
                self.assertIn(
                    "home/dot_config/mise/config.toml.tmpl", instructions
                )
                self.assertIn("version literal", instructions)
                self.assertIn("パッケージ名だけの除外へ広げず", instructions)
                self.assertIn(
                    "home/dot_config/mise/config.toml.tmpl", operations
                )
                for pattern in patterns:
                    self.assertNotIn(pattern, instructions)
                    self.assertNotIn(pattern, operations)

    def test_powershell_registers_kubectl_completer_for_k_alias(self) -> None:
        profile = POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8")

        self.assertIn("Get-CachedSourcePath -Name kubectl", profile)
        self.assertIn(
            "Get-Variable -Name __kubectlCompleterBlock -ValueOnly",
            profile,
        )
        self.assertIn(
            "Register-ArgumentCompleter -CommandName k -ScriptBlock $kubectlCompleter",
            profile,
        )


if __name__ == "__main__":
    unittest.main()
