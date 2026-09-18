"""Verify mise backend configuration and bootstrap behavior stay aligned."""

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
GIT_ATTRIBUTES_PATH = REPO_ROOT / ".gitattributes"
CONFIG_PATH = REPO_ROOT / "home/dot_config/mise/config.toml.tmpl"
LOCK_PATH = REPO_ROOT / "home/dot_config/mise/private_mise.lock"
MISE_SOURCE_PATH = REPO_ROOT / "home/dot_config/mise"
SYNC_SH_PATH = REPO_ROOT / "home/run_onchange_after_15-mise-sync-tools.sh.tmpl"
SYNC_PS1_PATH = REPO_ROOT / "home/run_onchange_after_15-mise-sync-tools.ps1.tmpl"
INSTALL_SH_PATH = REPO_ROOT / "home/run_once_after_20-mise-install.sh.tmpl"
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
MISE_LOCK_PLATFORM_CSV = ",".join(MISE_LOCK_PLATFORMS)
CARGO_MAKE_EXCLUDED_PLATFORM = ("linux", "arm64")
EXACT_LOCKS_SOURCE_PATTERN = re.compile(
    r"(?:remove_)?(?:external_)?exact_(?:private_)?(?:readonly_)?locks"
)

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
    "mise WARN  newer example-tool release 0.145.0 ignored by "
    "minimum_release_age (24h); latest eligible release is 0.144.6"
)
RECOVERED_FALLBACK_WARNING = (
    "mise WARN  mise-versions endpoint=github_release repo=sigstore/cosign "
    "tag=v3.1.2 outcome=failed status=502 fallback=true "
    'error="HTTP status server error (502 Bad Gateway): Failed to fetch GitHub release"'
)
MISE_GITHUB_TOKEN_ENV_NAMES = (
    "MISE_GITHUB_TOKEN",
    "GITHUB_API_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "TEST_GH_TOKEN",
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


def _zsh_mise_self_functions() -> str:
    zshrc = ZSHRC_PATH.read_text(encoding="utf-8")
    start = zshrc.index("mise-self-update() {")
    end = zshrc.index("\n# mise 管理ツールの一括更新", start)
    return zshrc[start:end]


def _mise_upgrade_function() -> str:
    zshrc = ZSHRC_PATH.read_text(encoding="utf-8")
    start = zshrc.index("mise-upgrade() {")
    end = zshrc.index("\n}\n\n{{ end -}}", start) + 2
    return zshrc[start:end]


def _powershell_mise_self_functions() -> str:
    profile = POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8")
    start = profile.index("function Invoke-MiseSelfUpdate {")
    end = profile.index("\n# mise 管理ツールの一括更新", start)
    return profile[start:end]


def _powershell_mise_upgrade_function() -> str:
    profile = POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8")
    start = profile.index("function Invoke-MiseUpgrade {")
    next_function = re.search(r"(?m)^function \S+", profile[start + 1 :])
    if next_function is None:
        raise AssertionError("Invoke-MiseUpgrade の次のトップレベル関数がありません")
    return profile[start : start + 1 + next_function.start()]


def _mise_token_test_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for name in MISE_GITHUB_TOKEN_ENV_NAMES:
        env.pop(name, None)
    env.update(overrides or {})
    return env


class MiseSelfUpdateCommandTests(unittest.TestCase):
    def test_zsh_mise_self_update_updates_binary_then_reshims(self) -> None:
        if shutil.which("zsh") is None:
            self.skipTest("zsh is required for mise-self-update tests")

        with tempfile.TemporaryDirectory() as temp_dir:
            script = (
                _zsh_mise_self_functions()
                + r"""
history_file="$1/history.txt"

mise() {
  print -r -- "mise $*" >> "$history_file"
  return 0
}

mise-self-update || exit 1
expected=$'mise self-update --yes --no-plugins\nmise reshim'
[[ "$(<"$history_file")" == "$expected" ]] || {
  print -u2 -- "$(<"$history_file")"
  exit 2
}
"""
            )
            result = subprocess.run(
                ["zsh", "-c", script, "mise-self-update-test", temp_dir],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_zsh_mise_self_update_resolves_token_without_persisting_it(self) -> None:
        if shutil.which("zsh") is None:
            self.skipTest("zsh is required for mise-self-update tests")

        cases = (
            (
                "mise-token",
                {"MISE_GITHUB_TOKEN": "mise-token"},
                None,
                "mise=mise-token;api=<unset>;github=<unset>;gh=<unset>",
                "after=mise-token",
                0,
            ),
            (
                "api-token",
                {"GITHUB_API_TOKEN": "api-token"},
                None,
                "mise=<unset>;api=api-token;github=<unset>;gh=<unset>",
                "after=<unset>",
                0,
            ),
            (
                "github-token",
                {"GITHUB_TOKEN": "github-token"},
                None,
                "mise=<unset>;api=<unset>;github=github-token;gh=<unset>",
                "after=<unset>",
                0,
            ),
            (
                "gh-environment",
                {"GH_TOKEN": "gh-token"},
                None,
                "mise=gh-token;api=<unset>;github=<unset>;gh=gh-token",
                "after=<unset>",
                0,
            ),
            (
                "gh-cli",
                {},
                "cli-token",
                "mise=cli-token;api=<unset>;github=<unset>;gh=<unset>",
                "after=<unset>",
                1,
            ),
            (
                "unauthenticated",
                {},
                None,
                "mise=<unset>;api=<unset>;github=<unset>;gh=<unset>",
                "after=<unset>",
                1,
            ),
        )
        for name, token_env, gh_token, expected_during, expected_after, gh_calls in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                script = (
                    _zsh_mise_self_functions()
                    + r"""
token_file="$1/token.txt"
gh_calls_file="$1/gh-calls.txt"

gh() {
  print -r -- "call" >> "$gh_calls_file"
  if [[ -n "${TEST_GH_TOKEN:-}" ]]; then
    print -r -- "${TEST_GH_TOKEN}"
    return 0
  fi
  return 1
}

mise() {
  if [[ "$1" == "self-update" ]]; then
    print -r -- \
      "mise=${MISE_GITHUB_TOKEN-<unset>};api=${GITHUB_API_TOKEN-<unset>};github=${GITHUB_TOKEN-<unset>};gh=${GH_TOKEN-<unset>}" \
      > "$token_file"
  fi
  return 0
}

mise-self-update || exit 1
print -r -- "after=${MISE_GITHUB_TOKEN-<unset>}" >> "$token_file"
"""
                )
                env = _mise_token_test_env(token_env)
                if gh_token is not None:
                    env["TEST_GH_TOKEN"] = gh_token
                result = subprocess.run(
                    ["zsh", "-c", script, "mise-self-update-token-test", temp_dir],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=env,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                token_lines = (
                    pathlib.Path(temp_dir) / "token.txt"
                ).read_text(encoding="utf-8").splitlines()
                calls_path = pathlib.Path(temp_dir) / "gh-calls.txt"
                actual_gh_calls = (
                    len(calls_path.read_text(encoding="utf-8").splitlines())
                    if calls_path.exists()
                    else 0
                )
                self.assertEqual(token_lines, [expected_during, expected_after])
                self.assertEqual(actual_gh_calls, gh_calls)

    def test_zsh_mise_self_update_does_not_reshim_after_update_failure(self) -> None:
        if shutil.which("zsh") is None:
            self.skipTest("zsh is required for mise-self-update tests")

        with tempfile.TemporaryDirectory() as temp_dir:
            script = (
                _zsh_mise_self_functions()
                + r"""
history_file="$1/history.txt"

mise() {
  print -r -- "mise $*" >> "$history_file"
  if [[ "$1" == "self-update" ]]; then
    return 9
  fi
  return 0
}

if mise-self-update; then
  print -u2 -- "mise-self-update unexpectedly succeeded"
  exit 1
fi
[[ "$(<"$history_file")" == "mise self-update --yes --no-plugins" ]] || {
  print -u2 -- "$(<"$history_file")"
  exit 2
}
"""
            )
            result = subprocess.run(
                ["zsh", "-c", script, "mise-self-update-failure-test", temp_dir],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_zsh_mise_self_update_fails_when_reshim_fails(self) -> None:
        if shutil.which("zsh") is None:
            self.skipTest("zsh is required for mise-self-update tests")

        with tempfile.TemporaryDirectory() as temp_dir:
            script = (
                _zsh_mise_self_functions()
                + r"""
history_file="$1/history.txt"

mise() {
  print -r -- "mise $*" >> "$history_file"
  if [[ "$1" == "reshim" ]]; then
    return 9
  fi
  return 0
}

if mise-self-update; then
  print -u2 -- "mise-self-update unexpectedly succeeded"
  exit 1
fi
expected=$'mise self-update --yes --no-plugins\nmise reshim'
[[ "$(<"$history_file")" == "$expected" ]] || {
  print -u2 -- "$(<"$history_file")"
  exit 2
}
"""
            )
            result = subprocess.run(
                ["zsh", "-c", script, "mise-self-update-reshim-test", temp_dir],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)

    def _run_powershell_mise_self_update(
        self,
        *,
        self_update_exit: int = 0,
        reshim_exit: int = 0,
        token_env: dict[str, str] | None = None,
        gh_token: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        if os.name != "nt":
            self.skipTest("Windows only")
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is required for PowerShell mise-self-update tests")

        with tempfile.TemporaryDirectory() as temp_dir:
            history_file = pathlib.Path(temp_dir) / "history.txt"
            script_file = pathlib.Path(temp_dir) / "test-mise-self-update.ps1"
            script_file.write_text(
                f"""
$PSStyle.OutputRendering = 'PlainText'
$historyPath = $env:TEST_HISTORY
$PSNativeCommandUseErrorActionPreference = $true
$script:ghCalls = 0
$script:selfUpdateTokens = $null
$script:reshimMiseToken = $null

function gh {{
    $script:ghCalls++
    if ($env:TEST_GH_TOKEN) {{
        $global:LASTEXITCODE = 0
        $env:TEST_GH_TOKEN
        return
    }}
    $global:LASTEXITCODE = 1
}}

function mise {{
    Add-Content -Path $historyPath -Value "mise $($args -join ' ')" -Encoding utf8
    if ($args[0] -eq 'self-update') {{
        $script:selfUpdateTokens = @{{
            mise = if (Test-Path Env:\\MISE_GITHUB_TOKEN) {{ $env:MISE_GITHUB_TOKEN }} else {{ $null }}
            api = if (Test-Path Env:\\GITHUB_API_TOKEN) {{ $env:GITHUB_API_TOKEN }} else {{ $null }}
            github = if (Test-Path Env:\\GITHUB_TOKEN) {{ $env:GITHUB_TOKEN }} else {{ $null }}
            gh = if (Test-Path Env:\\GH_TOKEN) {{ $env:GH_TOKEN }} else {{ $null }}
        }}
        $global:LASTEXITCODE = [int]$env:TEST_SELF_UPDATE_EXIT
        return
    }}
    if ($args[0] -eq 'reshim') {{
        $script:reshimMiseToken = if (Test-Path Env:\\MISE_GITHUB_TOKEN) {{ $env:MISE_GITHUB_TOKEN }} else {{ $null }}
        $global:LASTEXITCODE = [int]$env:TEST_RESHIM_EXIT
        return
    }}
    $global:LASTEXITCODE = 99
}}

{_powershell_mise_self_functions()}

Invoke-MiseSelfUpdate
$history = if (Test-Path $historyPath) {{ Get-Content -Path $historyPath }} else {{ @() }}
$result = @{{
    lastExitCode = $global:LASTEXITCODE
    history = @($history)
    selfUpdateTokens = $script:selfUpdateTokens
    reshimMiseToken = $script:reshimMiseToken
    ghCalls = $script:ghCalls
    miseTokenAfterPresent = Test-Path Env:\\MISE_GITHUB_TOKEN
    miseTokenAfter = if (Test-Path Env:\\MISE_GITHUB_TOKEN) {{ $env:MISE_GITHUB_TOKEN }} else {{ $null }}
}}
"RESULT_JSON=$($result | ConvertTo-Json -Compress)"
""",
                encoding="utf-8",
            )
            env = _mise_token_test_env(token_env)
            env.update(
                {
                    "TEST_HISTORY": str(history_file),
                    "TEST_SELF_UPDATE_EXIT": str(self_update_exit),
                    "TEST_RESHIM_EXIT": str(reshim_exit),
                }
            )
            if gh_token is not None:
                env["TEST_GH_TOKEN"] = gh_token
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
            return result, json.loads(match.group(1))

    def test_powershell_mise_self_update_updates_binary_then_reshims(self) -> None:
        result, state = self._run_powershell_mise_self_update()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["lastExitCode"], 0)
        self.assertEqual(
            state["history"],
            ["mise self-update --yes --no-plugins", "mise reshim"],
        )

    def test_powershell_mise_self_update_resolves_token_without_persisting_it(
        self,
    ) -> None:
        cases = (
            (
                "mise-token",
                {"MISE_GITHUB_TOKEN": "mise-token"},
                None,
                {"mise": "mise-token", "api": None, "github": None, "gh": None},
                "mise-token",
                True,
                "mise-token",
                0,
            ),
            (
                "api-token",
                {"GITHUB_API_TOKEN": "api-token"},
                None,
                {"mise": None, "api": "api-token", "github": None, "gh": None},
                None,
                False,
                None,
                0,
            ),
            (
                "github-token",
                {"GITHUB_TOKEN": "github-token"},
                None,
                {"mise": None, "api": None, "github": "github-token", "gh": None},
                None,
                False,
                None,
                0,
            ),
            (
                "gh-environment",
                {"GH_TOKEN": "gh-token"},
                None,
                {"mise": "gh-token", "api": None, "github": None, "gh": "gh-token"},
                None,
                False,
                None,
                0,
            ),
            (
                "gh-cli",
                {},
                "cli-token",
                {"mise": "cli-token", "api": None, "github": None, "gh": None},
                None,
                False,
                None,
                1,
            ),
            (
                "unauthenticated",
                {},
                None,
                {"mise": None, "api": None, "github": None, "gh": None},
                None,
                False,
                None,
                1,
            ),
        )
        for (
            name,
            token_env,
            gh_token,
            expected_during,
            expected_reshim_token,
            expected_after_present,
            expected_after,
            gh_calls,
        ) in cases:
            with self.subTest(name=name):
                result, state = self._run_powershell_mise_self_update(
                    token_env=token_env,
                    gh_token=gh_token,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(state["lastExitCode"], 0)
                self.assertEqual(state["selfUpdateTokens"], expected_during)
                self.assertEqual(state["reshimMiseToken"], expected_reshim_token)
                self.assertEqual(state["miseTokenAfterPresent"], expected_after_present)
                self.assertEqual(state["miseTokenAfter"], expected_after)
                self.assertEqual(state["ghCalls"], gh_calls)

    def test_powershell_mise_self_update_does_not_reshim_after_update_failure(
        self,
    ) -> None:
        result, state = self._run_powershell_mise_self_update(
            self_update_exit=9,
            token_env={"GH_TOKEN": "gh-token"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["lastExitCode"], 1)
        self.assertEqual(state["history"], ["mise self-update --yes --no-plugins"])
        self.assertFalse(state["miseTokenAfterPresent"])

    def test_powershell_mise_self_update_fails_when_reshim_fails(self) -> None:
        result, state = self._run_powershell_mise_self_update(reshim_exit=9)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["lastExitCode"], 1)
        self.assertEqual(
            state["history"],
            ["mise self-update --yes --no-plugins", "mise reshim"],
        )

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

    def test_mise_bootstrap_preserves_existing_installations(self) -> None:
        bootstrap_script = BOOTSTRAP_SH_PATH.read_text(encoding="utf-8")

        self.assertIn(
            'if ! existing_version="$("${mise_path}" --version)"; then',
            bootstrap_script,
        )
        self.assertIn(
            'if [ -e "${MISE_BIN_DIR}/mise" ] '
            '|| [ -L "${MISE_BIN_DIR}/mise" ]; then',
            bootstrap_script,
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

    def test_lockfile_v2_sidecars_are_complete_and_exact(self) -> None:
        chezmoi = shutil.which("chezmoi")
        if chezmoi is None:
            self.skipTest("chezmoi is required for sidecar source mapping tests")

        lock = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))
        referenced_sidecars: set[pathlib.PurePosixPath] = set()

        self.assertEqual(lock["lockfile_version"], 2)
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

    def test_exact_locks_source_attribute_order_matches_chezmoi(self) -> None:
        self.assertIsNotNone(EXACT_LOCKS_SOURCE_PATTERN.fullmatch("exact_locks"))
        self.assertIsNotNone(
            EXACT_LOCKS_SOURCE_PATTERN.fullmatch("exact_private_locks")
        )
        self.assertIsNone(
            EXACT_LOCKS_SOURCE_PATTERN.fullmatch("private_exact_locks")
        )

    def test_chezmoi_tracks_empty_sidecar_marker(self) -> None:
        chezmoi = shutil.which("chezmoi")
        if chezmoi is None:
            self.skipTest("chezmoi is required for sidecar marker mapping tests")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            source = root / "source"
            destination = root / "destination"
            locks_dir = destination / ".config/mise/locks"
            source.mkdir()
            locks_dir.mkdir(parents=True)
            (locks_dir / ".keep").touch()

            result = subprocess.run(
                [
                    chezmoi,
                    "--source",
                    str(source),
                    "--destination",
                    str(destination),
                    "add",
                    "--exact",
                    str(locks_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(
                (
                    source
                    / "dot_config/mise/exact_locks/empty_dot_keep"
                ).is_file()
            )

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

    def test_lock_sync_propagates_mise_failure(self) -> None:
        shell_script = SYNC_SH_PATH.read_text(encoding="utf-8")
        powershell_script = SYNC_PS1_PATH.read_text(encoding="utf-8")

        self.assertIn('exit "$sync_exit"', shell_script)
        self.assertIn("exit $syncExit", powershell_script)
        for script in (shell_script, powershell_script):
            self.assertIn("chezmoi apply", script)
            self.assertNotIn("chezmoi apply --force", script)
            self.assertNotIn("次回 chezmoi apply 時に再試行", script)

    def test_mise_upgrade_refreshes_sidecars_as_exact_directories(self) -> None:
        zshrc = ZSHRC_PATH.read_text(encoding="utf-8")
        profile = POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8")

        for script in (zshrc, profile):
            self.assertIn("chezmoi forget --force", script)
            self.assertIn("chezmoi add --exact", script)
            self.assertIn("aube-lock.yaml", script)
            self.assertIn("package.json", script)
            self.assertIn(".keep", script)
        self.assertIn('chezmoi source-path "$locks_dir"', zshrc)
        self.assertIn('source_locks_dir=""', zshrc)
        self.assertIn("updated_source_locks_dir=$(chezmoi source-path", zshrc)
        self.assertIn("grep -q '[^[:space:]]' \"$lockfile\"", zshrc)
        self.assertNotIn('"$aube_path" == *".."*', zshrc)
        self.assertIn("chezmoi source-path $locksDir", profile)
        self.assertIn("$resolvedSourceLocksDir =", profile)
        self.assertIn("$updatedSourceLocksDir =", profile)
        self.assertIn(
            "$PSNativeCommandUseErrorActionPreference = $false",
            profile,
        )
        self.assertIn(
            "$PSNativeCommandUseErrorActionPreference = "
            "$previousNativeErrorPreference",
            profile,
        )
        self.assertIn(
            r"""'(?m)^\s*aube\s*=\s*\{\s*path\s*=\s*"([^"]+)"'""",
            profile,
        )
        self.assertIn(
            "$aubePath -notmatch '^locks/[^/\\\\]+(?:/[^/\\\\]+)*\\z'",
            profile,
        )
        self.assertIn("[string]::IsNullOrWhiteSpace($lockText)", profile)

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

    def test_mise_upgrade_helpers_use_local_zsh_options(self) -> None:
        helpers = _mise_warning_helpers()

        self.assertEqual(helpers.count("emulate -L zsh"), 5)

    def _run_zsh_artifact_restore(
        self,
        lockfile: pathlib.Path,
        locks_dir: pathlib.Path,
        backup_dir: pathlib.Path,
        had_lockfile: bool,
        had_locks_dir: bool,
    ) -> subprocess.CompletedProcess[str]:
        if shutil.which("zsh") is None:
            self.skipTest("zsh is required for mise artifact restore tests")

        script = (
            _mise_warning_helpers()
            + '\n_mise_restore_artifacts "$1" "$2" "$3" "$4" "$5"\n'
        )
        return subprocess.run(
            [
                "zsh",
                "-c",
                script,
                "mise-artifact-restore-test",
                str(lockfile),
                str(locks_dir),
                str(backup_dir),
                "1" if had_lockfile else "0",
                "1" if had_locks_dir else "0",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_zsh_restores_existing_mise_artifacts_from_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            lockfile = root / "mise.lock"
            locks_dir = root / "locks"
            backup_dir = root / "backup"
            lockfile.write_text("generated", encoding="utf-8")
            (locks_dir / "generated").mkdir(parents=True)
            (locks_dir / "generated/aube-lock.yaml").write_text(
                "generated", encoding="utf-8"
            )
            (backup_dir / "locks/original").mkdir(parents=True)
            (backup_dir / "mise.lock").write_text("original", encoding="utf-8")
            (backup_dir / "locks/original/aube-lock.yaml").write_text(
                "original", encoding="utf-8"
            )

            result = self._run_zsh_artifact_restore(
                lockfile, locks_dir, backup_dir, True, True
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(lockfile.read_text(encoding="utf-8"), "original")
            self.assertFalse((locks_dir / "generated").exists())
            self.assertEqual(
                (locks_dir / "original/aube-lock.yaml").read_text(encoding="utf-8"),
                "original",
            )
            self.assertIn("lockfile と dependency sidecar を復元しました", result.stderr)

    def test_zsh_removes_generated_mise_artifacts_when_none_existed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            lockfile = root / "mise.lock"
            locks_dir = root / "locks"
            backup_dir = root / "backup"
            lockfile.write_text("generated", encoding="utf-8")
            (locks_dir / "generated").mkdir(parents=True)
            backup_dir.mkdir()

            result = self._run_zsh_artifact_restore(
                lockfile, locks_dir, backup_dir, False, False
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(lockfile.exists())
            self.assertFalse(locks_dir.exists())
            self.assertIn("lockfile と dependency sidecar を復元しました", result.stderr)

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

    def test_zsh_validates_flexibly_formatted_sidecar_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = pathlib.Path(temp_dir)
            lockfile = config_dir / "mise.lock"
            sidecar = config_dir / "locks/example/1"
            sidecar.mkdir(parents=True)
            (sidecar / "aube-lock.yaml").write_text("lock", encoding="utf-8")
            (sidecar / "package.json").write_text("{}", encoding="utf-8")
            lockfile.write_text(
                '  aube  =  {  path = "locks/example/1", digest = "sha256:test" }\n',
                encoding="utf-8",
            )

            result = self._run_zsh_sidecar_validation(lockfile, config_dir)

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_zsh_rejects_unparsed_sidecar_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = pathlib.Path(temp_dir)
            lockfile = config_dir / "mise.lock"
            lockfile.write_text(
                'aube = { digest = "sha256:test", path = "locks/example/1" }\n',
                encoding="utf-8",
            )

            result = self._run_zsh_sidecar_validation(lockfile, config_dir)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("すべて解析できません", result.stderr)

    def test_zsh_rejects_missing_lockfile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = pathlib.Path(temp_dir)

            result = self._run_zsh_sidecar_validation(
                config_dir / "missing.lock", config_dir
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("lockfile が存在しないか空です", result.stderr)

    def test_zsh_rejects_whitespace_only_lockfile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = pathlib.Path(temp_dir)
            lockfile = config_dir / "mise.lock"
            lockfile.write_text(" \n\t\n", encoding="utf-8")

            result = self._run_zsh_sidecar_validation(lockfile, config_dir)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("lockfile が存在しないか空です", result.stderr)

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

    def test_zsh_allows_double_dots_inside_sidecar_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = pathlib.Path(temp_dir)
            lockfile = config_dir / "mise.lock"
            sidecar = config_dir / "locks/example/1.0..2"
            sidecar.mkdir(parents=True)
            (sidecar / "aube-lock.yaml").write_text("lock", encoding="utf-8")
            (sidecar / "package.json").write_text("{}", encoding="utf-8")
            lockfile.write_text(
                'aube = { path = "locks/example/1.0..2", '
                'digest = "sha256:test" }\n',
                encoding="utf-8",
            )

            result = self._run_zsh_sidecar_validation(lockfile, config_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "1")

    def test_zsh_mise_upgrade_restores_source_and_target_on_readd_failure(
        self,
    ) -> None:
        if shutil.which("zsh") is None:
            self.skipTest("zsh is required for mise-upgrade rollback tests")

        with tempfile.TemporaryDirectory() as temp_dir:
            script = (
                _mise_warning_helpers()
                + "\n"
                + _mise_upgrade_function()
                + r"""
test_root="$1"
export HOME="${test_root}/home"
export TMPDIR="${test_root}/tmp"
# zsh は動的スコープなので、mise-upgrade の local と同名の変数をここで使うと
# スタブ内の参照が関数側の local を読んでしまう。tst_ を付けて衝突を避ける。
tst_lockfile="${HOME}/.config/mise/mise.lock"
tst_locks_dir="${HOME}/.config/mise/locks"
tst_source_home="${test_root}/source/home"
tst_source_lockfile="${tst_source_home}/dot_config/mise/private_mise.lock"
tst_source_locks_dir="${tst_source_home}/dot_config/mise/exact_locks"

mkdir -p "${tst_locks_dir}/original/1" \
  "${tst_source_locks_dir}/exact_original/exact_1" "$TMPDIR"
print -r -- "original-target-lock" > "$tst_lockfile"
print -r -- "original-target-package" \
  > "${tst_locks_dir}/original/1/package.json"
print -r -- "original-target-sidecar" \
  > "${tst_locks_dir}/original/1/aube-lock.yaml"
print -r -- "original-source-lock" > "$tst_source_lockfile"
print -r -- "original-source-package" \
  > "${tst_source_locks_dir}/exact_original/exact_1/package.json"
print -r -- "original-source-sidecar" \
  > "${tst_source_locks_dir}/exact_original/exact_1/aube-lock.yaml"

gh() {
  print -r -- "test-token"
}

mise() {
  if [[ "$1" == "upgrade" ]]; then
    return 0
  fi
  if [[ "$1" == "lock" ]]; then
    mkdir -p "${tst_locks_dir}/new/2"
    print -r -- 'lockfile_version = 2
[[tools."npm:test"]]
version = "2"
aube = { path = "locks/new/2", digest = "sha256:test" }' \
      > "$tst_lockfile"
    print -r -- "new-package" > "${tst_locks_dir}/new/2/package.json"
    print -r -- "new-sidecar" > "${tst_locks_dir}/new/2/aube-lock.yaml"
    return 0
  fi
  return 1
}

chezmoi() {
  if [[ "$1" == "source-path" ]]; then
    if (( $# == 1 )); then
      print -r -- "$tst_source_home"
    elif [[ "${@: -1}" == "$tst_lockfile" ]]; then
      print -r -- "$tst_source_lockfile"
    elif [[ "${@: -1}" == "$tst_locks_dir" &&
            -d "$tst_source_locks_dir" ]]; then
      print -r -- "$tst_source_locks_dir"
    else
      return 1
    fi
    return 0
  fi
  if [[ "$1" == "re-add" ]]; then
    command cp "$tst_lockfile" "$tst_source_lockfile"
    return 1
  fi
  if [[ "$1" == "forget" ]]; then
    command rm -rf "$tst_source_locks_dir"
    return 0
  fi
  return 1
}

git() {
  if [[ "$*" == *"rev-parse --abbrev-ref HEAD"* ]]; then
    print -r -- "main"
  fi
  return 0
}

if mise-upgrade; then
  print -u2 -- "mise-upgrade unexpectedly succeeded"
  exit 1
fi
[[ "$(<"$tst_lockfile")" == "original-target-lock" ]] || exit 2
[[ "$(<"${tst_locks_dir}/original/1/package.json")" == \
  "original-target-package" ]] || exit 3
[[ "$(<"$tst_source_lockfile")" == "original-source-lock" ]] || exit 4
[[ "$(<"${tst_source_locks_dir}/exact_original/exact_1/package.json")" == \
  "original-source-package" ]] || exit 5
"""
            )
            result = subprocess.run(
                [
                    "zsh",
                    "-c",
                    script,
                    "mise-upgrade-rollback-test",
                    temp_dir,
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "chezmoi 反映に失敗しました",
                result.stderr,
            )

    def _run_powershell_mise_upgrade(
        self,
        *,
        upgrade_output: str = "",
        lock_output: str = "",
        upgrade_exit: int = 0,
        lock_exit: int = 0,
        chezmoi_add_exit: int = 0,
        source_locks_managed: bool = True,
        source_path_after_add_exit: int = 0,
        lock_has_sidecars: bool = True,
        empty_lockfile: bool = False,
        aube_path: str = "locks/new/2",
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        if os.name != "nt":
            self.skipTest("Windows only")
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is required for PowerShell mise-upgrade tests")

        with tempfile.TemporaryDirectory() as temp_dir:
            test_root = pathlib.Path(temp_dir)
            lockfile = test_root / ".config/mise/mise.lock"
            locks_dir = lockfile.parent / "locks"
            lockfile.parent.mkdir(parents=True)
            lockfile.write_text("original-lock", encoding="utf-8")
            (locks_dir / "original/1").mkdir(parents=True)
            (locks_dir / "original/1/aube-lock.yaml").write_text(
                "original-sidecar", encoding="utf-8"
            )
            (locks_dir / "original/1/package.json").write_text(
                "original-package", encoding="utf-8"
            )
            source_home = test_root / "source/home"
            source_mise_dir = source_home / "dot_config/mise"
            source_locks_dir = source_mise_dir / "exact_private_locks"
            source_locks_leaf = source_locks_dir / "exact_original/exact_1"
            source_mise_dir.mkdir(parents=True)
            (source_mise_dir / "private_mise.lock").write_text(
                "original-source-lock", encoding="utf-8"
            )
            if source_locks_managed:
                source_locks_leaf.mkdir(parents=True)
                (source_locks_leaf / "aube-lock.yaml").write_text(
                    "original-source-sidecar", encoding="utf-8"
                )
                (source_locks_leaf / "package.json").write_text(
                    "original-source-package", encoding="utf-8"
                )
            history_file = test_root / "history.txt"
            script_file = test_root / "test-mise-upgrade.ps1"
            script_file.write_text(
                f"""
$PSStyle.OutputRendering = 'PlainText'
$historyPath = $env:TEST_HISTORY
$testLockfile = Join-Path $HOME ".config\\mise\\mise.lock"
$testLocksDir = Join-Path $HOME ".config\\mise\\locks"
$testSourceHome = Join-Path $HOME "source\\home"
$testSourceLockfile = Join-Path $testSourceHome "dot_config\\mise\\private_mise.lock"
$testSourceLocksDir = Join-Path $testSourceHome "dot_config\\mise\\exact_private_locks"
$script:sidecarAdded = $false
$PSNativeCommandUseErrorActionPreference = $true

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
        if ($env:TEST_EMPTY_LOCKFILE -eq '1') {{
            [System.IO.File]::WriteAllText($testLockfile, " `n")
        }}
        elseif ($env:TEST_LOCK_HAS_SIDECARS -eq '1') {{
            [System.IO.File]::WriteAllText(
                $testLockfile,
                "lockfile_version = 2`n" +
                "[[tools.`"npm:test`"]]`n" +
                "version = `"2`"`n" +
                "aube = {{ path = `"$($env:TEST_AUBE_PATH)`", " +
                "digest = `"sha256:test`" }}`n"
            )
            $newSidecar = Join-Path $testLocksDir "new\\2"
            New-Item -ItemType Directory -Path $newSidecar -Force | Out-Null
            [System.IO.File]::WriteAllText(
                (Join-Path $newSidecar "aube-lock.yaml"),
                'new-sidecar'
            )
            [System.IO.File]::WriteAllText(
                (Join-Path $newSidecar "package.json"),
                'new-package'
            )
        }}
        else {{
            [System.IO.File]::WriteAllText(
                $testLockfile,
                "lockfile_version = 2`n"
            )
        }}
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
        if ($args.Count -eq 1) {{
            $testSourceHome
        }}
        elseif ($args[-1] -eq $testLocksDir) {{
            if (-not (Test-Path -LiteralPath $testSourceLocksDir)) {{
                $global:LASTEXITCODE = 1
                return
            }}
            if ($script:sidecarAdded -and [int]$env:TEST_SOURCE_PATH_AFTER_ADD_EXIT -ne 0) {{
                $global:LASTEXITCODE = [int]$env:TEST_SOURCE_PATH_AFTER_ADD_EXIT
                return
            }}
            $testSourceLocksDir
        }}
        else {{
            $testSourceLockfile
        }}
        return
    }}
    if ($args[0] -eq 're-add') {{
        Copy-Item -LiteralPath $testLockfile -Destination $testSourceLockfile -Force
        return
    }}
    if ($args[0] -eq 'forget') {{
        Remove-Item -LiteralPath $testSourceLocksDir -Recurse -Force
        return
    }}
    if ($args[0] -eq 'add') {{
        if (Test-Path -LiteralPath (Join-Path $testLocksDir ".keep")) {{
            New-Item -ItemType Directory -Path $testSourceLocksDir -Force |
                Out-Null
            Copy-Item -LiteralPath (Join-Path $testLocksDir ".keep") `
                -Destination (
                    Join-Path $testSourceLocksDir "empty_dot_keep"
                ) -Force
        }}
        else {{
            $sourceSidecar = Join-Path $testSourceLocksDir "exact_new\\exact_2"
            New-Item -ItemType Directory -Path $sourceSidecar -Force | Out-Null
            Copy-Item -LiteralPath (Join-Path $testLocksDir "new\\2\\aube-lock.yaml") `
                -Destination $sourceSidecar -Force
            Copy-Item -LiteralPath (Join-Path $testLocksDir "new\\2\\package.json") `
                -Destination $sourceSidecar -Force
        }}
        $script:sidecarAdded = $true
        $global:LASTEXITCODE = [int]$env:TEST_CHEZMOI_ADD_EXIT
    }}
}}

function git {{
    Add-TestHistory "git $($args -join ' ')"
    $global:LASTEXITCODE = 0
    if ($args -contains 'rev-parse') {{
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
    sidecar = if (Test-Path (Join-Path $testLocksDir "new\\2\\package.json")) {{
        [System.IO.File]::ReadAllText(
            (Join-Path $testLocksDir "new\\2\\package.json")
        )
    }} elseif (Test-Path (Join-Path $testLocksDir "original\\1\\package.json")) {{
        [System.IO.File]::ReadAllText(
            (Join-Path $testLocksDir "original\\1\\package.json")
        )
    }} else {{
        $null
    }}
    target_keep = Test-Path (Join-Path $testLocksDir ".keep")
    source_lock = [System.IO.File]::ReadAllText($testSourceLockfile)
    source_sidecar = if (
        Test-Path (Join-Path $testSourceLocksDir "exact_new\\exact_2\\package.json")
    ) {{
        [System.IO.File]::ReadAllText(
            (Join-Path $testSourceLocksDir "exact_new\\exact_2\\package.json")
        )
    }} elseif (
        Test-Path (
            Join-Path $testSourceLocksDir "exact_original\\exact_1\\package.json"
        )
    ) {{
        [System.IO.File]::ReadAllText(
            (Join-Path $testSourceLocksDir "exact_original\\exact_1\\package.json")
        )
    }} else {{
        $null
    }}
    source_keep = Test-Path (Join-Path $testSourceLocksDir "empty_dot_keep")
    native_error_preference = $PSNativeCommandUseErrorActionPreference
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
                    "TEST_CHEZMOI_ADD_EXIT": str(chezmoi_add_exit),
                    "TEST_SOURCE_PATH_AFTER_ADD_EXIT": str(
                        source_path_after_add_exit
                    ),
                    "TEST_LOCK_HAS_SIDECARS": "1" if lock_has_sidecars else "0",
                    "TEST_EMPTY_LOCKFILE": "1" if empty_lockfile else "0",
                    "TEST_AUBE_PATH": aube_path,
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
                r"(?m)実行ログ:[\s|]*([^\r\n]+?\.tmp)\s*$",
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
                    state["lock"].replace("\r\n", "\n"),
                    (
                        'lockfile_version = 2\n[[tools."npm:test"]]\n'
                        'version = "2"\naube = { path = "locks/new/2", '
                        'digest = "sha256:test" }\n'
                    )
                    if allowed
                    else "original-lock",
                )
                self.assertEqual(
                    state["sidecar"],
                    "new-package" if allowed else "original-package",
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
        self.assertEqual(state["sidecar"], "new-package")
        self.assertEqual(state["source_sidecar"], "new-package")
        self.assertIn("回復済み", result.stdout + result.stderr)
        self.assertTrue(
            any(item.startswith("chezmoi re-add") for item in state["history"])
        )
        self.assertTrue(
            any(item.endswith(" add -A") for item in state["history"])
        )

    def test_powershell_mise_lock_restores_on_blocking_warning(self) -> None:
        result, state = self._run_powershell_mise_upgrade(
            lock_output="mise WARN failed to verify tool metadata"
        )

        self.assertEqual(result.returncode, 0)
        self.assertTrue(state["caught"])
        self.assertEqual(state["lock"], "original-lock")
        self.assertEqual(state["sidecar"], "original-package")
        self.assertEqual(state["source_lock"], "original-source-lock")
        self.assertEqual(state["source_sidecar"], "original-source-package")
        self.assertEqual(
            state["history"],
            [
                "gh auth token",
                "mise upgrade",
                f"mise lock --global --platform {MISE_LOCK_PLATFORM_CSV} --bump",
            ],
        )
        self.assertTrue(state["log_exists"])

    def test_powershell_mise_upgrade_restores_on_upgrade_failure(self) -> None:
        result, state = self._run_powershell_mise_upgrade(upgrade_exit=23)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(state["caught"])
        self.assertEqual(state["lock"], "original-lock")
        self.assertEqual(state["sidecar"], "original-package")
        self.assertEqual(state["history"], ["gh auth token", "mise upgrade"])
        self.assertTrue(state["log_exists"])

    def test_powershell_mise_upgrade_restores_on_lock_failure(self) -> None:
        result, state = self._run_powershell_mise_upgrade(lock_exit=29)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(state["caught"])
        self.assertEqual(state["lock"], "original-lock")
        self.assertEqual(state["sidecar"], "original-package")
        self.assertEqual(
            state["history"],
            [
                "gh auth token",
                "mise upgrade",
                f"mise lock --global --platform {MISE_LOCK_PLATFORM_CSV} --bump",
            ],
        )
        self.assertTrue(state["log_exists"])
        self.assertIn(
            "lockfile と dependency sidecar の再生成に失敗しました。実行ログを確認してください。",
            result.stdout + result.stderr,
        )
        self.assertNotIn("GITHUB_TOKEN の有効期限", result.stdout + result.stderr)

    def test_powershell_mise_upgrade_restores_source_on_sidecar_add_failure(
        self,
    ) -> None:
        result, state = self._run_powershell_mise_upgrade(chezmoi_add_exit=37)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(state["caught"])
        self.assertEqual(state["lock"], "original-lock")
        self.assertEqual(state["sidecar"], "original-package")
        self.assertEqual(state["source_lock"], "original-source-lock")
        self.assertEqual(state["source_sidecar"], "original-source-package")
        self.assertIn(
            "dependency sidecar の chezmoi add --exact に失敗しました",
            result.stdout + result.stderr,
        )

    def test_powershell_mise_upgrade_restores_source_when_post_add_path_fails(
        self,
    ) -> None:
        result, state = self._run_powershell_mise_upgrade(
            source_path_after_add_exit=41
        )

        self.assertEqual(result.returncode, 0)
        self.assertTrue(state["caught"])
        self.assertEqual(state["lock"], "original-lock")
        self.assertEqual(state["sidecar"], "original-package")
        self.assertEqual(state["source_lock"], "original-source-lock")
        self.assertEqual(state["source_sidecar"], "original-source-package")
        self.assertIn(
            "更新後の dependency sidecar の chezmoi ソースパスを取得できません",
            result.stdout + result.stderr,
        )
        self.assertNotIn(
            "空の文字列であるため、引数をバインドできません",
            result.stdout + result.stderr,
        )

    def test_powershell_mise_upgrade_adds_initially_unmanaged_sidecars(
        self,
    ) -> None:
        result, state = self._run_powershell_mise_upgrade(
            source_locks_managed=False
        )

        self.assertEqual(result.returncode, 0)
        self.assertFalse(state["caught"])
        self.assertEqual(state["source_sidecar"], "new-package")
        self.assertFalse(
            any("forget --force" in item for item in state["history"])
        )

    def test_powershell_mise_upgrade_tracks_empty_sidecar_directory(
        self,
    ) -> None:
        result, state = self._run_powershell_mise_upgrade(
            lock_has_sidecars=False
        )

        self.assertEqual(result.returncode, 0)
        self.assertFalse(state["caught"])
        self.assertIsNone(state["sidecar"])
        self.assertIsNone(state["source_sidecar"])
        self.assertTrue(state["target_keep"])
        self.assertTrue(state["source_keep"])
        self.assertTrue(
            any("forget --force" in item for item in state["history"])
        )
        self.assertTrue(state["native_error_preference"])

    def test_powershell_mise_upgrade_rejects_empty_lockfile(self) -> None:
        result, state = self._run_powershell_mise_upgrade(empty_lockfile=True)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(state["caught"])
        self.assertEqual(state["lock"], "original-lock")
        self.assertEqual(state["sidecar"], "original-package")
        self.assertIn(
            "lockfile が存在しないか空です",
            result.stdout + result.stderr,
        )

    def test_powershell_mise_upgrade_rejects_backslash_sidecar_path(
        self,
    ) -> None:
        result, state = self._run_powershell_mise_upgrade(
            aube_path=r"locks/..\..\evil"
        )

        self.assertEqual(result.returncode, 0)
        self.assertTrue(state["caught"])
        self.assertEqual(state["lock"], "original-lock")
        self.assertEqual(state["sidecar"], "original-package")
        self.assertIn(
            r"dependency sidecar path が不正です: locks/..\..\evil",
            result.stdout + result.stderr,
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

    def test_trust_policy_excludes_stay_version_scoped(self) -> None:
        config = CONFIG_PATH.read_text(encoding="utf-8")
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
