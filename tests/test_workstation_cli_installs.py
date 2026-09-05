"""P3 workstation CLI のprovider linkとLinux直接導入を検証する。"""

from __future__ import annotations

import hashlib
import io
import os
import pathlib
import shutil
import stat
import struct
import subprocess
import tarfile
import tempfile
import tomllib
import unittest
import zipfile

from tests.chezmoi_test_helpers import execute_template


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "home"
DATA_PATH = SOURCE_ROOT / ".chezmoidata.toml"
BASH = shutil.which("bash")
PWSH = shutil.which("pwsh")

TOOLS = {
    "bat": {"number": 61, "command": "bat", "version": "0.26.1"},
    "fzf": {"number": 63, "command": "fzf", "version": "0.74.3"},
    "ghq": {"number": 64, "command": "ghq", "version": "1.10.1"},
    "gitleaks": {"number": 65, "command": "gitleaks", "version": "8.30.1"},
    "lefthook": {"number": 67, "command": "lefthook", "version": "2.1.12"},
    "ripgrep": {"number": 68, "command": "rg", "version": "15.2.0"},
    "shellcheck": {"number": 69, "command": "shellcheck", "version": "0.11.0"},
    "zoxide": {"number": 70, "command": "zoxide", "version": "0.10.0"},
}
LINUX_PLATFORMS = ("linux-amd64", "linux-arm64")
WINDOWS_PLATFORMS = ("windows-amd64", "windows-arm64")


def _load_data() -> dict:
    return tomllib.loads(DATA_PATH.read_text(encoding="utf-8"))


def _script_path(name: str, suffix: str) -> pathlib.Path:
    spec = TOOLS[name]
    return SOURCE_ROOT / f"run_after_{spec['number']}-install-{name}.{suffix}.tmpl"


def _render(
    name: str, suffix: str, os_name: str, arch: str, data: dict | None = None
) -> str:
    override = {
        "chezmoi": {"os": os_name, "arch": arch},
        "codespaces": False,
        "devcontainer": False,
        "isWSL": False,
        "windowsUser": "",
        "corpUser": "",
    }
    if data:
        override.update(data)
    result = execute_template(_script_path(name, suffix), override, SOURCE_ROOT)
    if result.returncode != 0:
        raise AssertionError(f"{name}.{suffix} render failed: {result.stderr}")
    return result.stdout


def _write_executable(path: pathlib.Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("utf-8"))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _binary_body(
    command: str, version: str, exit_code: int = 0, help_output: str | None = None
) -> str:
    output = {
        "bat": f"bat {version}",
        "fzf": f"{version} (synthetic)",
        "ghq": f"ghq version {version} (rev:synthetic)",
        "gitleaks": version,
        "lefthook": version,
        "rg": f"ripgrep {version}",
        "shellcheck": f"ShellCheck - shell script analysis tool\\nversion: {version}",
        "zoxide": f"zoxide {version}",
    }[command]
    help_text = help_output or {
        "fzf": "fzf - command-line fuzzy finder\\n--preview COMMAND",
        "gitleaks": "Gitleaks detects hardcoded secrets",
        "lefthook": "lefthook - Git hooks manager\\ninstall hooks",
    }.get(command, f"{command} help")
    expected = "version" if command == "lefthook" else "--version"
    return (
        "#!/bin/sh\n"
        'printf "%s\\n" "$PWD" >> "${PROBE_CWDS:?}"\n'
        f'if [ "$#" -eq 1 ] && [ "$1" = "--help" ]; then '
        f"printf '%b\\n' '{help_text}'; exit 0; fi\n"
        f'[ "$#" -eq 1 ] && [ "$1" = "{expected}" ] || exit 64\n'
        f"printf '%b\\n' '{output}'\n"
        f"exit {exit_code}\n"
    )


def _make_archive(archive: str, entry: str, body: str) -> bytes:
    payload = body.encode("utf-8")
    if archive == "raw":
        return payload
    output = io.BytesIO()
    if archive == "tar.gz":
        with tarfile.open(fileobj=output, mode="w:gz") as bundle:
            info = tarfile.TarInfo(entry)
            info.mode = 0o755
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))
    elif archive == "zip":
        with zipfile.ZipFile(output, "w") as bundle:
            info = zipfile.ZipInfo(entry)
            info.external_attr = 0o755 << 16
            bundle.writestr(info, payload)
    else:
        raise AssertionError(archive)
    return output.getvalue()


def _extract_between(source: str, start: str, end: str) -> str:
    return source[source.index(start) : source.index(end)]


class DeclarationAndRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _load_data()

    def test_owned_declarations_have_linux_assets_and_winget_platforms(self) -> None:
        asset_keys = {
            "file", "url", "sha256", "archive", "entry", "executableArch", "emulated"
        }
        winget_keys = {"architecture", "executableArch", "emulated"}
        for name, spec in TOOLS.items():
            tool = self.data[name]
            with self.subTest(tool=name):
                self.assertEqual(tool["version"], spec["version"])
                self.assertEqual(tool["minimumVersion"], spec["version"])
                self.assertEqual(set(tool["assets"]), set(LINUX_PLATFORMS))
                self.assertEqual(
                    set(tool["winget"]["platforms"]), set(WINDOWS_PLATFORMS)
                )
            for platform, asset in tool["assets"].items():
                with self.subTest(tool=name, platform=platform):
                    self.assertEqual(set(asset), asset_keys)
                    self.assertRegex(asset["sha256"], r"^[0-9a-f]{64}$")
                    self.assertTrue(asset["url"].startswith("https://"))
                    self.assertIn(spec["version"], asset["url"])
                    self.assertEqual(
                        asset["executableArch"], platform.rsplit("-", 1)[1]
                    )
                    self.assertFalse(asset["emulated"])
            for platform, declaration in tool["winget"]["platforms"].items():
                with self.subTest(tool=name, platform=platform):
                    self.assertEqual(set(declaration), winget_keys)
                    if name == "shellcheck" and platform == "windows-arm64":
                        self.assertEqual(
                            declaration,
                            {
                                "architecture": "x64",
                                "executableArch": "amd64",
                                "emulated": True,
                            },
                        )
                    else:
                        expected_arch = platform.rsplit("-", 1)[1]
                        self.assertEqual(
                            declaration["architecture"],
                            "x64" if expected_arch == "amd64" else "arm64",
                        )
                        self.assertEqual(
                            declaration["executableArch"], expected_arch
                        )
                        self.assertFalse(declaration["emulated"])

    @unittest.skipUnless(BASH, "bash is required for template syntax checks")
    def test_all_posix_templates_render_and_pass_bash_n(self) -> None:
        for name in TOOLS:
            for os_name, arch in (
                ("linux", "amd64"),
                ("linux", "arm64"),
                ("darwin", "arm64"),
            ):
                rendered = _render(name, "sh", os_name, arch)
                result = subprocess.run(
                    [BASH, "-n"],
                    input=rendered,
                    capture_output=True,
                    encoding="utf-8",
                    check=False,
                )
                with self.subTest(tool=name, os=os_name, arch=arch):
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_provider_routes_are_owned_and_never_upgrade_packages(self) -> None:
        for name, spec in TOOLS.items():
            mac = _render(name, "sh", "darwin", "arm64")
            windows = _render(name, "ps1", "windows", "amd64")
            with self.subTest(tool=name):
                self.assertIn("/opt/homebrew/bin/brew", mac)
                self.assertIn(
                    f"/opt/${{brew_package}}/bin/${{tool_name}}", mac
                )
                self.assertNotRegex(mac, r"\bbrew\s+(install|upgrade)\b")
                self.assertNotRegex(mac, r"\b(apt|apt-get)\b")
                self.assertIn("Microsoft\\WinGet\\Links", windows)
                self.assertIn("Microsoft\\WinGet\\Packages", windows)
                self.assertIn(
                    "Microsoft.Winget.Source_8wekyb3d8bbwe",
                    windows,
                )
                self.assertIn(
                    '"$root/$wingetId`_$wingetSourceIdentifier/"',
                    windows,
                )
                self.assertIn(self.data[name]["winget"]["id"], windows)
                self.assertIn("[System.IO.File]::Move($stagedLink, $target, $true)", windows)
                self.assertNotIn("Move-Item -LiteralPath $stagedLink", windows)
                self.assertNotRegex(windows, r"winget\s+(install|upgrade)")
                self.assertNotIn("Get-Command", windows)
                self.assertNotIn(".local\\share\\mise\\shims", windows)

    @unittest.skipUnless(PWSH, "pwsh is unavailable; WinGet ownership fixtures skipped")
    def test_windows_provider_accepts_only_official_winget_source_root(self) -> None:
        rendered = _render("bat", "ps1", "windows", "amd64")
        functions = _extract_between(
            rendered,
            "function ConvertTo-NormalizedPath",
            "function Test-BinaryArchitecture",
        )
        winget_id = self.data["bat"]["winget"]["id"]
        source_id = "Microsoft.Winget.Source_8wekyb3d8bbwe"

        for directory, expected in (
            (f"{winget_id}_{source_id}", True),
            (f"{winget_id}_Foreign.Source", False),
        ):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as temp:
                root = pathlib.Path(temp)
                packages = root / "Packages"
                links = root / "Links"
                payload = packages / directory / "bat.exe"
                payload.parent.mkdir(parents=True)
                links.mkdir()
                payload.write_bytes(b"fixture")
                alias = links / "bat.exe"
                alias.symlink_to(payload)
                quote = lambda value: str(value).replace("'", "''")
                script = f"""
$providerAlias = '{quote(alias)}'
$packagesRoot = '{quote(packages)}'
$wingetId = '{winget_id}'
$toolName = 'bat'
$wingetSourceIdentifier = '{source_id}'
{functions}
try {{
    Get-ProviderExecutable | Write-Output
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
                self.assertEqual(result.returncode == 0, expected, result.stdout)

    def test_linux_templates_pin_declared_assets_and_exact_versions(self) -> None:
        for name in TOOLS:
            for platform in LINUX_PLATFORMS:
                _, arch = platform.split("-", 1)
                rendered = _render(name, "sh", "linux", arch)
                asset = self.data[name]["assets"][platform]
                with self.subTest(tool=name, platform=platform):
                    self.assertIn(asset["url"], rendered)
                    self.assertIn(asset["sha256"], rendered)
                    self.assertIn(asset["entry"], rendered)
                    self.assertIn("binary_has_architecture", rendered)
                    self.assertIn("did not report", rendered)

    def test_user_contracts_for_ghcd_precommit_and_completion_remain_present(self) -> None:
        zsh = (SOURCE_ROOT / "dot_zshrc.tmpl").read_text(encoding="utf-8")
        powershell = (SOURCE_ROOT / "PowerShell_profile.ps1.tmpl").read_text(
            encoding="utf-8"
        )
        hook = (SOURCE_ROOT / "dot_local/bin/executable_gitleaks-pre-commit").read_text(
            encoding="utf-8"
        )
        self.assertIn("ghq list -p | fzf", zsh)
        self.assertIn("ghq list -p | fzf", powershell)
        self.assertIn("_cached_source zoxide zoxide", zsh)
        self.assertIn('"${home_root}/.local/bin/gitleaks"', hook)
        self.assertIn('"${home_root}/.local/bin/gitleaks.exe"', hook)
        self.assertIn("git --pre-commit --staged", hook)

    @unittest.skipUnless(PWSH, "pwsh is unavailable; Windows parser checks skipped")
    def test_windows_templates_parse(self) -> None:
        for name in TOOLS:
            rendered = _render(name, "ps1", "windows", "amd64")
            with tempfile.TemporaryDirectory() as temp:
                script = pathlib.Path(temp) / "installer.ps1"
                script.write_text(rendered, encoding="utf-8", newline="\n")
                quoted = str(script).replace("'", "''")
                result = subprocess.run(
                    [
                        PWSH,
                        "-NoProfile",
                        "-Command",
                        "$e=$null; "
                        "[System.Management.Automation.Language.Parser]::ParseFile("
                        f"'{quoted}',[ref]$null,[ref]$e)|Out-Null; "
                        "if($e.Count){$e|% Message;exit 1}",
                    ],
                    capture_output=True,
                    encoding="utf-8",
                    check=False,
                )
                with self.subTest(tool=name):
                    self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


@unittest.skipIf(os.name == "nt", "POSIX behavior is not tested through Git Bash")
@unittest.skipUnless(BASH, "bash is required for POSIX behavior tests")
class LinuxDirectInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _load_data()

    def _fixture(
        self, root: pathlib.Path, name: str, *, version: str | None = None,
        exit_code: int = 0, missing_entry: bool = False
    ) -> tuple[pathlib.Path, dict]:
        spec = TOOLS[name]
        asset = dict(self.data[name]["assets"]["linux-amd64"])
        entry = "missing/entry" if missing_entry else asset["entry"]
        body = _binary_body(spec["command"], version or spec["version"], exit_code)
        payload = _make_archive(asset["archive"], entry, body)
        fixture = root / asset["file"]
        fixture.write_bytes(payload)
        asset["sha256"] = hashlib.sha256(payload).hexdigest()
        return fixture, {
            name: {
                "version": spec["version"],
                "minimumVersion": spec["version"],
                "assets": {"linux-amd64": asset},
            }
        }

    def _prepare(
        self, root: pathlib.Path, name: str, fixture: pathlib.Path,
        override: dict, *, curl_fail: bool = False, wrong_arch: bool = False
    ) -> tuple[pathlib.Path, pathlib.Path, dict[str, str]]:
        home = root / "home"
        bin_dir = home / ".local/bin"
        stubs = root / "stubs"
        bin_dir.mkdir(parents=True)
        stubs.mkdir()
        _write_executable(
            stubs / "curl",
            "#!/bin/sh\n"
            "printf 'called\\n' >> \"$STUB_CURL_CALLS\"\n"
            "[ \"$STUB_CURL_FAIL\" = 0 ] || exit 22\n"
            "output=''\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "  case \"$1\" in -o) output=$2; shift 2;; *) shift;; esac\n"
            "done\n"
            "cp \"$STUB_CURL_SOURCE\" \"$output\"\n",
        )
        _write_executable(
            stubs / "od",
            "#!/bin/sh\n"
            "binary=''\n"
            "for argument do binary=$argument; done\n"
            "machine='3e 00'\n"
            "case \"${STUB_WRONG_ARCH_SCOPE}:${binary}\" in\n"
            "  all:*|candidate:*/extracted/*) machine='b7 00' ;;\n"
            "esac\n"
            "printf '%s%s\\n' ' 7f 45 4c 46 02 01 01 00 00 00 00 00 00 00 00 00"
            "' \" 02 00 ${machine}\"\n",
        )
        rendered = _render(name, "sh", "linux", "amd64", override)
        script = root / "installer.sh"
        _write_executable(script, rendered)
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "PATH": f"{stubs}{os.pathsep}{env['PATH']}",
                "STUB_CURL_CALLS": str(root / "curl-calls"),
                "STUB_CURL_FAIL": "1" if curl_fail else "0",
                "STUB_CURL_SOURCE": str(fixture),
                "STUB_WRONG_ARCH_SCOPE": "candidate" if wrong_arch else "none",
                "PROBE_CWDS": str(root / "probe-cwds"),
            }
        )
        return script, home, env

    def test_fresh_install_and_exact_local_fast_path(self) -> None:
        for name, spec in TOOLS.items():
            with self.subTest(tool=name), tempfile.TemporaryDirectory() as temp:
                root = pathlib.Path(temp)
                fixture, override = self._fixture(root, name)
                script, home, env = self._prepare(root, name, fixture, override)
                result = subprocess.run(
                    [BASH, str(script)], env=env, cwd=root, capture_output=True,
                    encoding="utf-8", check=False
                )
                target = home / ".local/bin" / spec["command"]
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(target.is_file())
                calls = pathlib.Path(env["STUB_CURL_CALLS"])
                self.assertEqual(calls.read_text(encoding="utf-8"), "called\n")
                calls.unlink()
                env["STUB_CURL_FAIL"] = "1"
                second = subprocess.run(
                    [BASH, str(script)], env=env, cwd=root, capture_output=True,
                    encoding="utf-8", check=False
                )
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertFalse(calls.exists())

    def test_recognized_older_cli_is_updated(self) -> None:
        for name, spec in TOOLS.items():
            with self.subTest(tool=name), tempfile.TemporaryDirectory() as temp:
                root = pathlib.Path(temp)
                fixture, override = self._fixture(root, name)
                script, home, env = self._prepare(root, name, fixture, override)
                target = home / ".local/bin" / spec["command"]
                _write_executable(
                    target, _binary_body(spec["command"], "0.0.1")
                )
                result = subprocess.run(
                    [BASH, str(script)], env=env, cwd=root, capture_output=True,
                    encoding="utf-8", check=False
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(
                    spec["version"], target.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    pathlib.Path(env["STUB_CURL_CALLS"]).read_text(encoding="utf-8"),
                    "called\n",
                )

    def test_download_hash_version_exit_and_arch_failures_preserve_old_target(self) -> None:
        for name, spec in TOOLS.items():
            for failure in ("download", "hash", "version", "exit", "arch"):
                with self.subTest(tool=name, failure=failure), tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    fixture, override = self._fixture(
                        root, name,
                        version="9.9.9" if failure == "version" else None,
                        exit_code=1 if failure == "exit" else 0,
                    )
                    if failure == "hash":
                        override[name]["assets"]["linux-amd64"]["sha256"] = "0" * 64
                    script, home, env = self._prepare(
                        root, name, fixture, override,
                        curl_fail=failure == "download",
                        wrong_arch=failure == "arch",
                    )
                    target = home / ".local/bin" / spec["command"]
                    _write_executable(
                        target, _binary_body(spec["command"], "0.0.1")
                    )
                    old_bytes = target.read_bytes()
                    result = subprocess.run(
                        [BASH, str(script)], env=env, cwd=root, capture_output=True,
                        encoding="utf-8", check=False
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(target.read_bytes(), old_bytes)

    def test_unrecognized_regular_files_are_rejected_before_network(self) -> None:
        for name, spec in TOOLS.items():
            for kind in ("non-executable", "unknown-output", "failed-probe", "wrong-cpu"):
                with self.subTest(tool=name, kind=kind), tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    fixture, override = self._fixture(root, name)
                    script, home, env = self._prepare(
                        root, name, fixture, override,
                    )
                    if kind == "wrong-cpu":
                        env["STUB_WRONG_ARCH_SCOPE"] = "all"
                    target = home / ".local/bin" / spec["command"]
                    if kind == "non-executable":
                        target.write_text("foreign bytes", encoding="utf-8")
                    elif kind == "unknown-output":
                        _write_executable(
                            target,
                            "#!/bin/sh\n"
                            'printf "%s\\n" "$PWD" >> "${PROBE_CWDS:?}"\n'
                            "printf '%s\\n' 'unrelated 0.0.1'\n",
                        )
                    elif kind == "failed-probe":
                        _write_executable(
                            target,
                            _binary_body(spec["command"], "0.0.1", exit_code=1),
                        )
                    else:
                        _write_executable(
                            target, _binary_body(spec["command"], "0.0.1")
                        )
                    old_bytes = target.read_bytes()
                    result = subprocess.run(
                        [BASH, str(script)], env=env, cwd=root, capture_output=True,
                        encoding="utf-8", check=False
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(target.read_bytes(), old_bytes)
                    self.assertFalse(
                        pathlib.Path(env["STUB_CURL_CALLS"]).exists()
                    )

    def test_same_semver_from_another_cli_is_rejected_before_network(self) -> None:
        for name in ("fzf", "gitleaks", "lefthook"):
            spec = TOOLS[name]
            with self.subTest(tool=name), tempfile.TemporaryDirectory() as temp:
                root = pathlib.Path(temp)
                fixture, override = self._fixture(root, name)
                script, home, env = self._prepare(root, name, fixture, override)
                target = home / ".local/bin" / spec["command"]
                _write_executable(
                    target,
                    _binary_body(
                        spec["command"],
                        spec["version"],
                        help_output="unrelated command with no expected features",
                    ),
                )
                old_bytes = target.read_bytes()
                result = subprocess.run(
                    [BASH, str(script)], env=env, cwd=root, capture_output=True,
                    encoding="utf-8", check=False
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(target.read_bytes(), old_bytes)
                self.assertFalse(
                    pathlib.Path(env["STUB_CURL_CALLS"]).exists()
                )

    def test_missing_archive_entry_is_nonzero(self) -> None:
        for name, spec in TOOLS.items():
            if self.data[name]["assets"]["linux-amd64"]["archive"] == "raw":
                continue
            with self.subTest(tool=name), tempfile.TemporaryDirectory() as temp:
                root = pathlib.Path(temp)
                fixture, override = self._fixture(root, name, missing_entry=True)
                script, home, env = self._prepare(root, name, fixture, override)
                result = subprocess.run(
                    [BASH, str(script)], env=env, cwd=root, capture_output=True,
                    encoding="utf-8", check=False
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((home / ".local/bin" / spec["command"]).exists())

    def test_foreign_entries_and_mise_directory_links_are_rejected_without_network(self) -> None:
        for name, spec in TOOLS.items():
            for kind in ("foreign-symlink", "directory", "mise-directory"):
                with self.subTest(tool=name, kind=kind), tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    fixture, override = self._fixture(root, name)
                    script, home, env = self._prepare(root, name, fixture, override)
                    target = home / ".local/bin" / spec["command"]
                    if kind == "foreign-symlink":
                        target.symlink_to(root / "foreign")
                    elif kind == "directory":
                        target.mkdir()
                    else:
                        shim = home / ".local/share/mise/shims" / spec["command"]
                        shim.mkdir(parents=True)
                        (shim / "keep").write_text("keep", encoding="utf-8")
                        target.symlink_to(shim, target_is_directory=True)
                    result = subprocess.run(
                        [BASH, str(script)], env=env, cwd=root, capture_output=True,
                        encoding="utf-8", check=False
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(pathlib.Path(env["STUB_CURL_CALLS"]).exists())

    def test_dangling_mise_link_is_replaced(self) -> None:
        for name, spec in TOOLS.items():
            with self.subTest(tool=name), tempfile.TemporaryDirectory() as temp:
                root = pathlib.Path(temp)
                fixture, override = self._fixture(root, name)
                script, home, env = self._prepare(root, name, fixture, override)
                shim = home / ".local/share/mise/shims" / spec["command"]
                shim.parent.mkdir(parents=True)
                target = home / ".local/bin" / spec["command"]
                target.symlink_to(shim)
                result = subprocess.run(
                    [BASH, str(script)], env=env, cwd=root, capture_output=True,
                    encoding="utf-8", check=False
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(target.is_file())
                self.assertFalse(target.is_symlink())


@unittest.skipIf(os.name == "nt", "POSIX behavior is not tested through Git Bash")
@unittest.skipUnless(BASH, "bash is required for macOS provider tests")
class MacProviderTests(unittest.TestCase):
    def _prepare(
        self, root: pathlib.Path, name: str, *, version: str | None = None
    ) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, dict[str, str]]:
        spec = TOOLS[name]
        home = root / "home"
        prefix = root / "homebrew"
        stubs = root / "stubs"
        (home / ".local/bin").mkdir(parents=True)
        stubs.mkdir()
        package = _load_data()[name]["homebrew"]["package"]
        provider = prefix / "opt" / package / "bin" / spec["command"]
        _write_executable(
            provider,
            _binary_body(spec["command"], version or spec["version"]),
        )
        brew = root / "brew"
        _write_executable(
            brew,
            "#!/bin/sh\n"
            "printf 'called\\n' >> \"$STUB_BREW_CALLS\"\n"
            "printf '%s\\n' \"$STUB_BREW_PREFIX\"\n",
        )
        _write_executable(
            stubs / "od",
            "#!/bin/sh\nprintf '%s\\n' ' cf fa ed fe 0c 00 00 01'\n",
        )
        rendered = _render(name, "sh", "darwin", "arm64").replace(
            "brew_bin=/opt/homebrew/bin/brew", f"brew_bin={brew}"
        ).replace(
            '[ "${brew_prefix}" = "/opt/homebrew" ]',
            f'[ "${{brew_prefix}}" = "{prefix}" ]',
        )
        script = root / "installer.sh"
        _write_executable(script, rendered)
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "PATH": f"{stubs}{os.pathsep}{env['PATH']}",
                "STUB_BREW_PREFIX": str(prefix),
                "STUB_BREW_CALLS": str(root / "brew-calls"),
                "PROBE_CWDS": str(root / "probe-cwds"),
            }
        )
        return script, home, provider, env

    def test_brew_owned_provider_creates_stable_native_link_without_package_update(self) -> None:
        for name, spec in TOOLS.items():
            with self.subTest(tool=name), tempfile.TemporaryDirectory() as temp:
                root = pathlib.Path(temp)
                script, home, provider, env = self._prepare(root, name)
                result = subprocess.run(
                    [BASH, str(script)], env=env, cwd=root, capture_output=True,
                    encoding="utf-8", check=False
                )
                target = home / ".local/bin" / spec["command"]
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(target.is_symlink())
                self.assertEqual(target.readlink(), provider)

    def test_brew_provider_below_minimum_is_rejected(self) -> None:
        for name, spec in TOOLS.items():
            with self.subTest(tool=name), tempfile.TemporaryDirectory() as temp:
                root = pathlib.Path(temp)
                script, home, _, env = self._prepare(root, name, version="0.0.1")
                result = subprocess.run(
                    [BASH, str(script)], env=env, cwd=root, capture_output=True,
                    encoding="utf-8", check=False
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((home / ".local/bin" / spec["command"]).exists())

    def test_brew_provider_does_not_replace_foreign_entries(self) -> None:
        for name, spec in TOOLS.items():
            for kind in ("file", "directory", "symlink"):
                with self.subTest(tool=name, kind=kind), tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    script, home, _, env = self._prepare(root, name)
                    target = home / ".local/bin" / spec["command"]
                    if kind == "file":
                        target.write_text("foreign", encoding="utf-8")
                    elif kind == "directory":
                        target.mkdir()
                    else:
                        target.symlink_to(root / "foreign")
                    result = subprocess.run(
                        [BASH, str(script)], env=env, cwd=root, capture_output=True,
                        encoding="utf-8", check=False
                    )
                    self.assertNotEqual(result.returncode, 0)
                    if kind == "file":
                        self.assertEqual(
                            target.read_text(encoding="utf-8"), "foreign"
                        )
                    elif kind == "directory":
                        self.assertTrue(target.is_dir())
                    else:
                        self.assertEqual(target.readlink(), root / "foreign")


class HeaderParserTests(unittest.TestCase):
    @unittest.skipUnless(BASH, "bash is required for ELF parser tests")
    def test_elf_parser_accepts_only_declared_cpu(self) -> None:
        source = _render("bat", "sh", "linux", "amd64")
        function = _extract_between(
            source, "binary_has_architecture() {", "tool_version() {"
        )
        cases = (
            (0x3E, "amd64", True),
            (0xB7, "amd64", False),
            (0xB7, "arm64", True),
            (None, "amd64", False),
        )
        for machine, arch, expected in cases:
            with self.subTest(machine=machine, arch=arch), tempfile.TemporaryDirectory() as temp:
                root = pathlib.Path(temp)
                binary = root / "binary"
                if machine is None:
                    binary.write_bytes(b"not an executable")
                else:
                    header = bytearray(64)
                    header[:6] = b"\x7fELF\x02\x01"
                    header[18:20] = struct.pack("<H", machine)
                    binary.write_bytes(header)
                checker = root / "check.sh"
                _write_executable(
                    checker,
                    "#!/usr/bin/env bash\nset -euo pipefail\nplatform_os=linux\n"
                    + function
                    + f'\nbinary_has_architecture "$1" "{arch}"\n',
                )
                result = subprocess.run(
                    [BASH, str(checker), str(binary)], check=False
                )
                self.assertEqual(result.returncode == 0, expected)

    @unittest.skipUnless(PWSH, "pwsh is unavailable; PE parser checks skipped")
    def test_pe_parser_accepts_x64_and_rejects_arm64_for_x64_declaration(self) -> None:
        source = _render("bat", "ps1", "windows", "amd64")
        function = _extract_between(
            source, "function Test-BinaryArchitecture", "function Get-ToolVersion"
        )
        for machine, expected in ((0x8664, True), (0xAA64, False)):
            with self.subTest(machine=machine), tempfile.TemporaryDirectory() as temp:
                root = pathlib.Path(temp)
                binary = root / "binary.exe"
                header = bytearray(128)
                header[:2] = b"MZ"
                header[0x3C:0x40] = struct.pack("<I", 0x40)
                header[0x40:0x44] = b"PE\0\0"
                header[0x44:0x46] = struct.pack("<H", machine)
                binary.write_bytes(header)
                checker = root / "check.ps1"
                quoted = str(binary).replace("'", "''")
                checker.write_text(
                    "$executableArch='amd64'\n" + function +
                    f"\nif(Test-BinaryArchitecture -Path '{quoted}'){{exit 0}}else{{exit 1}}\n",
                    encoding="utf-8", newline="\n"
                )
                result = subprocess.run(
                    [PWSH, "-NoProfile", "-File", str(checker)], check=False
                )
                self.assertEqual(result.returncode == 0, expected)


if __name__ == "__main__":
    unittest.main()
