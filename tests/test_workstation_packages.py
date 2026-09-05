"""Verify P3 workstation OS-package bootstrap contracts."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import tomllib
import unittest

from tests.chezmoi_test_helpers import execute_template


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "home"
DATA_PATH = SOURCE_ROOT / ".chezmoidata.toml"
PACKAGE_SH = SOURCE_ROOT / "run_once_before_10-install-packages.sh.tmpl"
TOOLS_PS1 = SOURCE_ROOT / "run_once_after_30-install-tools.ps1.tmpl"

P3_DATA_KEYS = {
    "1password": "onePassword",
    "bat": "bat",
    "cargo-make": "cargoMake",
    "fzf": "fzf",
    "ghq": "ghq",
    "gitleaks": "gitleaks",
    "golangci-lint": "golangciLint",
    "lefthook": "lefthook",
    "ripgrep": "ripgrep",
    "shellcheck": "shellcheck",
    "zoxide": "zoxide",
}
HOMEBREW_TOOLS = {
    "1password",
    "bat",
    "cargo-make",
    "fzf",
    "ghq",
    "gitleaks",
    "lefthook",
    "ripgrep",
    "shellcheck",
    "zoxide",
}
WINGET_TOOLS = {
    "bat",
    "fzf",
    "ghq",
    "gitleaks",
    "golangci-lint",
    "lefthook",
    "ripgrep",
    "shellcheck",
    "zoxide",
}
COMMAND_NAMES = {
    "1password": "op",
    "bat": "bat",
    "cargo-make": "cargo-make",
    "fzf": "fzf",
    "ghq": "ghq",
    "gitleaks": "gitleaks",
    "golangci-lint": "golangci-lint",
    "lefthook": "lefthook",
    "ripgrep": "rg",
    "shellcheck": "shellcheck",
    "zoxide": "zoxide",
}
PWSH = shutil.which("pwsh")


def _render(path: pathlib.Path, os_name: str, arch: str) -> str:
    result = execute_template(
        path,
        {
            "chezmoi": {"os": os_name, "arch": arch},
            "codespaces": False,
            "devcontainer": False,
            "isWSL": False,
            "windowsUser": "",
            "corpUser": "",
        },
        SOURCE_ROOT,
    )
    if result.returncode != 0:
        raise AssertionError(f"{path.name} failed to render: {result.stderr}")
    return result.stdout


def _marked_block(source: str, marker: str) -> str:
    start = source.index(f"# >>> {marker}")
    end = source.index(f"# <<< {marker}", start)
    return source[start:end]


def _write_executable(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)


class WorkstationDeclarationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = tomllib.loads(DATA_PATH.read_text(encoding="utf-8"))

    def test_p3_versions_distinguish_direct_release_and_provider_floor(self) -> None:
        for tool, data_key in P3_DATA_KEYS.items():
            declaration = self.data[data_key]
            with self.subTest(tool=tool):
                self.assertRegex(declaration["version"], r"^\d+\.\d+\.\d+$")
                self.assertRegex(
                    declaration["minimumVersion"],
                    r"^\d+\.\d+\.\d+$",
                )

    def test_homebrew_provider_contract_is_exact(self) -> None:
        configured = {
            tool
            for tool, data_key in P3_DATA_KEYS.items()
            if "homebrew" in self.data[data_key]
        }
        self.assertEqual(configured, HOMEBREW_TOOLS)
        for tool in HOMEBREW_TOOLS:
            provider = self.data[P3_DATA_KEYS[tool]]["homebrew"]
            with self.subTest(tool=tool):
                self.assertRegex(provider["package"], r"^[A-Za-z0-9@+_.-]+$")
                self.assertIn(provider["kind"], {"formula", "cask"})
        self.assertEqual(
            self.data["onePassword"]["homebrew"]["kind"],
            "cask",
        )
        self.assertNotIn("homebrew", self.data["golangciLint"])

    def test_winget_architecture_contract_has_only_shellcheck_emulation(self) -> None:
        configured = {
            tool
            for tool, data_key in P3_DATA_KEYS.items()
            if "winget" in self.data[data_key]
        }
        self.assertEqual(configured, WINGET_TOOLS)

        emulated = set()
        for tool in WINGET_TOOLS:
            provider = self.data[P3_DATA_KEYS[tool]]["winget"]
            self.assertRegex(provider["id"], r"^[A-Za-z0-9_.-]+$")
            self.assertEqual(
                set(provider["platforms"]),
                {"windows-amd64", "windows-arm64"},
            )
            for platform, asset in provider["platforms"].items():
                with self.subTest(tool=tool, platform=platform):
                    if asset["emulated"]:
                        emulated.add((tool, platform))
                    else:
                        expected = platform.rsplit("-", maxsplit=1)[1]
                        self.assertEqual(asset["executableArch"], expected)
                        self.assertEqual(
                            asset["architecture"],
                            "x64" if expected == "amd64" else "arm64",
                        )

        self.assertEqual(emulated, {("shellcheck", "windows-arm64")})
        shellcheck_arm = self.data["shellcheck"]["winget"]["platforms"][
            "windows-arm64"
        ]
        self.assertEqual(shellcheck_arm["architecture"], "x64")
        self.assertEqual(shellcheck_arm["executableArch"], "amd64")

    def test_direct_asset_emulation_is_only_onepassword_windows_arm64(self) -> None:
        emulated = set()
        for tool, data_key in P3_DATA_KEYS.items():
            for platform, asset in self.data[data_key].get("assets", {}).items():
                if asset["emulated"]:
                    emulated.add((tool, platform))

        self.assertEqual(emulated, {("1password", "windows-arm64")})
        assets = self.data["onePassword"]["assets"]
        arm64 = assets["windows-arm64"]
        amd64 = assets["windows-amd64"]
        self.assertEqual(arm64["executableArch"], "amd64")
        for key in ("file", "url", "sha256", "archive", "entry"):
            with self.subTest(key=key):
                self.assertEqual(arm64[key], amd64[key])


class MacHomebrewBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rendered = _render(PACKAGE_SH, "darwin", "arm64")
        cls.block = _marked_block(cls.rendered, "p3-homebrew")
        cls.data = tomllib.loads(DATA_PATH.read_text(encoding="utf-8"))

    def test_block_uses_provider_owned_paths_and_targeted_operations(self) -> None:
        self.assertIn(
            '"${P3_BREW_BIN}" --prefix "${package}"',
            self.block,
        )
        self.assertIn(
            '[ "${P3_BREW_PREFIX_RAW}" = "${P3_EXPECTED_BREW_PREFIX}" ]',
            self.block,
        )
        self.assertIn(
            '[ "${prefix}" = "${P3_EXPECTED_BREW_PREFIX}/opt/${package}" ]',
            self.block,
        )
        self.assertIn('"${prefix}/bin/${command_name}"', self.block)
        self.assertIn('"${P3_BREW_BIN}" list --formula --versions', self.block)
        self.assertIn('"${P3_BREW_BIN}" list --cask --versions', self.block)
        self.assertIn('"${P3_BREW_BIN}" install "${package}"', self.block)
        self.assertIn('"${P3_BREW_BIN}" upgrade "${package}"', self.block)
        self.assertIn(
            '"${P3_BREW_BIN}" install --cask "${package}"',
            self.block,
        )
        self.assertIn(
            '"${P3_BREW_BIN}" upgrade --cask "${package}"',
            self.block,
        )
        self.assertNotIn("brew upgrade --greedy", self.block)
        self.assertNotIn("brew upgrade\n", self.block)
        self.assertNotIn("command -v", self.block)
        self.assertIn('od -An -tx1 -N8 "${binary}"', self.block)
        self.assertIn("cffaedfe0c000001", self.block)
        self.assertNotIn("gitleaks|lefthook)", self.block)
        self.assertIn(
            'lefthook)\n      output="$("${binary}" version',
            self.block,
        )
        self.assertIn(
            "printf '%s\\n' \"${output}\" | grep -E "
            "'^[0-9]+(\\.[0-9]+){2}$'",
            self.block,
        )
        self.assertIn(
            'output="$("${binary}" make --version 2>/dev/null)"',
            self.block,
        )
        self.assertIn(
            "grep -Eq '^cargo-make [0-9]+(\\.[0-9]+){2}$'",
            self.block,
        )
        self.assertIn(
            'output="$("${binary}" --version 2>/dev/null)"',
            self.block,
        )

    def test_block_embeds_only_homebrew_minimums(self) -> None:
        for tool in HOMEBREW_TOOLS:
            declaration = self.data[P3_DATA_KEYS[tool]]
            with self.subTest(tool=tool):
                self.assertIn(declaration["minimumVersion"], self.block)
                self.assertIn(declaration["homebrew"]["package"], self.block)
        self.assertNotIn("golangci-lint", self.block)

    def _run_fixture(
        self,
        *,
        missing: set[str] = frozenset(),
        old: set[str] = frozenset(),
        wrong_arch: set[str] = frozenset(),
        wrong_prefix: bool = False,
        wrong_formula_prefix: bool = False,
        multiline_version: set[str] = frozenset(),
        multiline_makers: bool = False,
        invalid_cargo_version_format: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is required")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            prefix = root / "homebrew"
            state = root / "state"
            stub_bin = root / "stub-bin"
            log = root / "brew.log"
            state.mkdir()
            stub_bin.mkdir()
            reported_prefix = root / "foreign-homebrew" if wrong_prefix else prefix
            reported_prefix.mkdir(parents=True, exist_ok=True)

            for tool in HOMEBREW_TOOLS:
                data_key = P3_DATA_KEYS[tool]
                declaration = self.data[data_key]
                package = declaration["homebrew"]["package"]
                command = COMMAND_NAMES[tool]
                if tool not in missing:
                    (state / package).touch()
                if declaration["homebrew"]["kind"] == "cask":
                    binary = prefix / "Caskroom" / package / "1.0.0" / command
                    alias = prefix / "bin" / command
                else:
                    binary = prefix / "Cellar" / package / "1.0.0" / "bin" / command
                    opt = prefix / "opt" / package
                    opt.parent.mkdir(parents=True, exist_ok=True)
                    opt.symlink_to(prefix / "Cellar" / package / "1.0.0")
                    alias = None
                version = "0.0.0" if tool in old else declaration["minimumVersion"]
                suffix = "\nunexpected" if tool in multiline_version else ""
                _write_executable(
                    binary,
                    f"#!/bin/sh\nprintf '%s\\n' '{version}{suffix}'\n",
                )
                if alias is not None:
                    alias.parent.mkdir(parents=True, exist_ok=True)
                    alias.symlink_to(binary)
                if tool == "cargo-make":
                    cargo_prefix = "" if invalid_cargo_version_format else "cargo-make "
                    _write_executable(
                        binary,
                        "#!/bin/sh\n"
                        '[ "$*" = "make --version" ] || exit 64\n'
                        f"printf '%s\\n' '{cargo_prefix}{version}{suffix}'\n",
                    )
                    makers_suffix = "\nunexpected" if multiline_makers else ""
                    makers_prefix = (
                        "" if invalid_cargo_version_format else "cargo-make "
                    )
                    makers = (
                        prefix
                        / "Cellar"
                        / package
                        / "1.0.0"
                        / "bin"
                        / "makers"
                    )
                    _write_executable(
                        makers,
                        "#!/bin/sh\n"
                        '[ "$*" = "--version" ] || exit 64\n'
                        f"printf '%s\\n' "
                        f"'{makers_prefix}{declaration['minimumVersion']}"
                        f"{makers_suffix}'\n",
                    )

            brew_stub = f"""#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$P3_BREW_LOG"
case "$1" in
  --prefix)
    if [ "$#" -eq 1 ]; then
      printf '%s\\n' "$BREW_STUB_PREFIX"
    elif [ "${{P3_WRONG_FORMULA_PREFIX:-0}}" = 1 ]; then
      printf '%s/Cellar/%s/1.0.0\\n' "$BREW_STUB_PREFIX" "$2"
    else
      printf '%s/opt/%s\\n' "$BREW_STUB_PREFIX" "$2"
    fi
    ;;
  list)
    package="$4"
    [ -f "$P3_BREW_STATE/$package" ]
    printf '%s 1.0.0\\n' "$package"
    ;;
  install|upgrade)
    action="$1"
    shift
    if [ "${{1:-}}" = "--cask" ]; then shift; fi
    package="$1"
    : > "$P3_BREW_STATE/$package"
    if [ "$package" = "{self.data['gitleaks']['homebrew']['package']}" ]; then
      cat > "$BREW_STUB_PREFIX/Cellar/$package/1.0.0/bin/gitleaks" <<'EOF'
#!/bin/sh
printf '%s\\n' '{self.data["gitleaks"]["minimumVersion"]}'
EOF
      chmod 755 "$BREW_STUB_PREFIX/Cellar/$package/1.0.0/bin/gitleaks"
    fi
    ;;
esac
"""
            _write_executable(prefix / "bin" / "brew", brew_stub)
            _write_executable(stub_bin / "uname", "#!/bin/sh\necho arm64\n")
            wrong = " ".join(sorted(wrong_arch))
            od_stub = f"""#!/bin/sh
case "$*" in
  *bat*) case " {wrong} " in *" bat "*) echo 'cf fa ed fe 07 00 00 01'; exit 0 ;; esac ;;
esac
echo 'cf fa ed fe 0c 00 00 01'
"""
            _write_executable(stub_bin / "od", od_stub)

            fixture_block = self.block.replace(
                "P3_BREW_BIN=/opt/homebrew/bin/brew",
                f"P3_BREW_BIN='{prefix / 'bin' / 'brew'}'",
            )
            script = (
                "set -euo pipefail\n"
                "version_ge() { [ \"$1\" = \"$2\" ]; }\n"
                + fixture_block
            )
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{stub_bin}{os.pathsep}{env.get('PATH', '')}",
                    "BREW_STUB_PREFIX": str(reported_prefix),
                    "P3_BREW_STATE": str(state),
                    "P3_BREW_LOG": str(log),
                    "P3_WRONG_FORMULA_PREFIX": "1" if wrong_formula_prefix else "0",
                }
            )
            result = subprocess.run(
                [bash],
                input=script,
                check=False,
                capture_output=True,
                encoding="utf-8",
                env=env,
            )
            lines = (
                log.read_text(encoding="utf-8").splitlines()
                if log.exists()
                else []
            )
            return result, lines

    def test_fixture_installs_missing_and_upgrades_only_below_minimum(self) -> None:
        result, calls = self._run_fixture(missing={"fzf"}, old={"gitleaks"})
        package_calls = [
            call
            for call in calls
            if call.startswith("install ") or call.startswith("upgrade ")
        ]

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(package_calls, ["install fzf", "upgrade gitleaks"])

    def test_fixture_rejects_wrong_cpu_without_package_operation(self) -> None:
        result, calls = self._run_fixture(wrong_arch={"bat"})
        package_calls = [
            call
            for call in calls
            if call.startswith("install ") or call.startswith("upgrade ")
        ]

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("native macOS architecture", result.stderr)
        self.assertEqual(package_calls, [])

    def test_fixture_rejects_unexpected_homebrew_prefix(self) -> None:
        result, calls = self._run_fixture(wrong_prefix=True)
        package_calls = [
            call
            for call in calls
            if call.startswith("install ") or call.startswith("upgrade ")
        ]

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reported an unexpected prefix", result.stderr)
        self.assertEqual(package_calls, [])

    def test_fixture_rejects_nonstable_formula_prefix(self) -> None:
        result, calls = self._run_fixture(wrong_formula_prefix=True)
        package_calls = [
            call
            for call in calls
            if call.startswith("install ") or call.startswith("upgrade ")
        ]

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("formula bat", result.stderr)
        self.assertEqual(package_calls, [])

    def test_fixture_rejects_multiline_onepassword_version(self) -> None:
        result, calls = self._run_fixture(multiline_version={"1password"})
        package_calls = [
            call
            for call in calls
            if call.startswith("install ") or call.startswith("upgrade ")
        ]

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not determine", result.stderr)
        self.assertEqual(package_calls, [])

    def test_fixture_rejects_multiline_cargo_make_versions(self) -> None:
        for kwargs in (
            {"multiline_version": {"cargo-make"}},
            {"multiline_makers": True},
        ):
            with self.subTest(kwargs=kwargs):
                result, calls = self._run_fixture(**kwargs)
                package_calls = [
                    call
                    for call in calls
                    if call.startswith("install ") or call.startswith("upgrade ")
                ]

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("could not determine", result.stderr)
                self.assertEqual(package_calls, [])

    def test_fixture_rejects_invalid_cargo_make_version_format(self) -> None:
        result, calls = self._run_fixture(invalid_cargo_version_format=True)
        package_calls = [
            call
            for call in calls
            if call.startswith("install ") or call.startswith("upgrade ")
        ]

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not determine", result.stderr)
        self.assertEqual(package_calls, [])


class LinuxSourceBuildPrerequisiteTests(unittest.TestCase):
    def test_c_compiler_toolchain_is_arm64_source_build_only(self) -> None:
        arm64 = _render(PACKAGE_SH, "linux", "arm64")
        amd64 = _render(PACKAGE_SH, "linux", "amd64")

        self.assertIn("build-essential \\\n", arm64)
        self.assertNotIn("build-essential \\\n", amd64)


class WindowsWinGetBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.amd64 = _render(TOOLS_PS1, "windows", "amd64")
        cls.arm64 = _render(TOOLS_PS1, "windows", "arm64")
        cls.amd64_block = _marked_block(cls.amd64, "p3-winget")
        cls.arm64_block = _marked_block(cls.arm64, "p3-winget")
        cls.data = tomllib.loads(DATA_PATH.read_text(encoding="utf-8"))

    def test_block_uses_exact_user_scope_targeted_commands(self) -> None:
        for block in (self.amd64_block, self.arm64_block):
            self.assertIn(
                "install --id $Spec.Id --exact --source $p3WinGetSource --scope user "
                "--architecture $Spec.Architecture",
                block,
            )
            self.assertIn(
                "upgrade --id $Spec.Id --exact --source $p3WinGetSource --scope user "
                "--architecture $Spec.Architecture",
                block,
            )
            self.assertIn(
                "list --id $Id --exact --source $p3WinGetSource --scope $Scope",
                block,
            )
            self.assertIn(
                "$p3WinGetSourceIdentifier = "
                "'Microsoft.Winget.Source_8wekyb3d8bbwe'",
                block,
            )
            self.assertIn("--accept-package-agreements", block)
            self.assertIn("--accept-source-agreements", block)
            self.assertIn("--disable-interactivity", block)
            self.assertNotIn("upgrade --all", block)
            self.assertNotIn("Get-Command", block)

    def test_block_rejects_machine_scope_foreign_alias_and_wrong_cpu(self) -> None:
        for block in (self.amd64_block, self.arm64_block):
            self.assertIn("-Scope machine", block)
            self.assertIn("refusing an implicit scope or privilege change", block)
            self.assertIn(
                "exists without the expected registered WinGet user package",
                block,
            )
            self.assertIn("refusing to replace it", block)
            self.assertIn(
                "Join-Path $env:LOCALAPPDATA 'Microsoft\\WinGet\\Links'",
                block,
            )
            self.assertIn(
                "Join-Path $env:LOCALAPPDATA 'Microsoft\\WinGet\\Packages'",
                block,
            )
            self.assertIn("is not owned by package", block)
            self.assertIn(
                "Get-P3ExecutableVersion -Path $aliasPath",
                block,
            )
            self.assertIn("$expectedPackageDirectory =", block)
            self.assertIn("$packageDirectory.Equals(", block)
            self.assertNotIn('"$Id`_"', block)
            self.assertLess(
                block.index("$preflightBinary = Get-P3WinGetExecutable"),
                block.index(
                    "$userInstalled = Test-P3WinGetPackage"
                ),
            )

    def test_list_only_treats_official_not_found_code_as_missing(self) -> None:
        for block in (self.amd64_block, self.arm64_block):
            self.assertIn("$p3WinGetNoApplicationsFound = -1978335212", block)
            self.assertIn(
                "if ($exitCode -eq $p3WinGetNoApplicationsFound)",
                block,
            )
            self.assertIn("$output -join [Environment]::NewLine", block)

    @unittest.skipUnless(PWSH, "pwsh is unavailable; WinGet list fixtures skipped")
    def test_list_distinguishes_missing_from_source_failures_for_both_scopes(self) -> None:
        start = self.amd64_block.index("$p3WinGetSource =")
        end = self.amd64_block.index("function Get-P3PeArchitecture")
        function_source = self.amd64_block[start:end]
        fake = r"""
$p3WinGetExe = {
    param([Parameter(ValueFromRemainingArguments = $true)][object[]]$Arguments)
    $global:capturedArguments = @($Arguments | ForEach-Object { "$_" })
    if ($env:TEST_WINGET_OUTPUT) { Write-Output $env:TEST_WINGET_OUTPUT }
    $global:LASTEXITCODE = [int]$env:TEST_WINGET_EXIT
}
"""
        for scope in ("user", "machine"):
            for exit_code, expected, should_throw in (
                (0, True, False),
                (-1978335212, False, False),
                (-1978335174, None, True),
                (-1978335163, None, True),
                (-1978335143, None, True),
            ):
                with self.subTest(scope=scope, exit_code=exit_code):
                    script = (
                        fake
                        + function_source
                        + f"""
try {{
    $result = Test-P3WinGetPackage -Id 'Example.Tool' -Scope '{scope}'
    Write-Output "RESULT:$result"
    Write-Output "ARGS:$($global:capturedArguments -join ' ')"
}} catch {{
    Write-Output "ERROR:$($_.Exception.Message)"
    exit 23
}}
"""
                    )
                    env = os.environ.copy()
                    env["TEST_WINGET_EXIT"] = str(exit_code)
                    env["TEST_WINGET_OUTPUT"] = "source diagnostic"
                    result = subprocess.run(
                        [PWSH, "-NoProfile", "-Command", "-"],
                        input=script,
                        capture_output=True,
                        encoding="utf-8",
                        check=False,
                        env=env,
                    )
                    if should_throw:
                        self.assertEqual(23, result.returncode, result.stdout)
                        self.assertIn("source diagnostic", result.stdout)
                    else:
                        self.assertEqual(0, result.returncode, result.stderr)
                        self.assertIn(f"RESULT:{expected}", result.stdout)
                    self.assertIn(
                        f"--source winget --scope {scope}",
                        result.stdout,
                    )

    @unittest.skipUnless(PWSH, "pwsh is unavailable; WinGet preflight fixture skipped")
    def test_foreign_source_alias_is_rejected_before_winget_invocation(self) -> None:
        start = self.amd64_block.index("function Test-P3WinGetPackage")
        end = self.amd64_block.index("$p3WinGetSpecs =")
        functions = self.amd64_block[start:end]
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            links = root / "Links"
            packages = root / "Packages"
            calls = root / "winget-calls"
            payload = packages / "sharkdp.bat_Foreign.Source" / "bat.exe"
            payload.parent.mkdir(parents=True)
            links.mkdir()
            payload.write_bytes(b"fixture")
            alias = links / "bat.exe"
            alias.symlink_to(payload)
            fake_winget = root / "winget.ps1"
            fake_winget.write_text(
                f"Add-Content -LiteralPath '{calls}' -Value called\nexit 99\n",
                encoding="utf-8",
                newline="\n",
            )
            quote = lambda value: str(value).replace("'", "''")
            script = f"""
$p3WinGetExe = '{quote(fake_winget)}'
$p3WinGetLinkDir = '{quote(links)}'
$p3WinGetPackagesDir = '{quote(packages)}'
$p3WinGetSource = 'winget'
$p3WinGetSourceIdentifier = 'Microsoft.Winget.Source_8wekyb3d8bbwe'
$p3WinGetNoApplicationsFound = -1978335212
{functions}
$spec = [pscustomobject]@{{
    Name = 'bat'
    MinimumVersion = '0.26.1'
    Id = 'sharkdp.bat'
    Command = 'bat'
    VersionArguments = @('--version')
    Architecture = 'x64'
    ExecutableArch = 'amd64'
    Emulated = $false
}}
try {{
    Install-P3WinGetPackage -Spec $spec
}} catch {{
    Write-Output $_.Exception.Message
    exit 23
}}
"""
            result = subprocess.run(
                [PWSH, "-NoProfile", "-Command", "-"],
                input=script,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(23, result.returncode, result.stdout)
            self.assertIn("from source winget", result.stdout)
            self.assertFalse(calls.exists())

    def test_rendered_architectures_follow_the_declarations(self) -> None:
        for tool in WINGET_TOOLS:
            declaration = self.data[P3_DATA_KEYS[tool]]
            for platform, block in (
                ("windows-amd64", self.amd64_block),
                ("windows-arm64", self.arm64_block),
            ):
                asset = declaration["winget"]["platforms"][platform]
                with self.subTest(tool=tool, platform=platform):
                    self.assertIn(f"Id = '{declaration['winget']['id']}'", block)
                    self.assertIn(
                        f"MinimumVersion = '{declaration['minimumVersion']}'",
                        block,
                    )
                    self.assertIn(
                        f"Architecture = '{asset['architecture']}'",
                        block,
                    )
                    self.assertIn(
                        f"ExecutableArch = '{asset['executableArch']}'",
                        block,
                    )

    def test_shellcheck_is_the_only_windows_arm64_x64_request(self) -> None:
        self.assertEqual(
            self.arm64_block.count("Architecture = 'x64'"),
            1,
        )
        shellcheck = self.data["shellcheck"]["winget"]["platforms"][
            "windows-arm64"
        ]
        self.assertTrue(shellcheck["emulated"])


if __name__ == "__main__":
    unittest.main()
