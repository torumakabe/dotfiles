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

ALLOWED_WARNING = (
    "mise WARN  newer codex release 0.145.0 ignored by "
    "minimum_release_age (24h); latest eligible release is 0.144.6"
)
WARNING_CASES = (
    ("allowed", f"{ALLOWED_WARNING}\n", True),
    ("allowed-with-ansi", f"\x1b[33m{ALLOWED_WARNING}\x1b[0m\n", True),
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
    def test_dotnet_alias_matches_lock_backend(self) -> None:
        config = CONFIG_PATH.read_text(encoding="utf-8")
        lock = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))

        dotnet_entries = lock["tools"]["dotnet"]
        self.assertEqual(len(dotnet_entries), 1)
        self.assertEqual(_tool_alias(config, "dotnet"), dotnet_entries[0]["backend"])

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
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("処理を中止する警告", result.stderr)
                if name == "allowed-with-ansi":
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

    def test_mise_lock_platform_contract_stays_aligned(self) -> None:
        zshrc = ZSHRC_PATH.read_text(encoding="utf-8")
        profile = POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8")
        operations = OPERATIONS_PATH.read_text(encoding="utf-8")
        troubleshooting = TROUBLESHOOTING_PATH.read_text(encoding="utf-8")

        self.assertIn(
            f"mise lock --global --platform {MISE_LOCK_PLATFORM_CSV}",
            zshrc,
        )
        self.assertIn(
            f'-Arguments @("lock", "--global", "--platform", "{MISE_LOCK_PLATFORM_CSV}")',
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
                    {MISE_LOCK_PLATFORM_CSV},
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
