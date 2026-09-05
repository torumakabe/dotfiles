"""P2 core cloud tools の直接導入を合成 fixture だけで検証する。"""

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

PLATFORMS = (
    "linux-amd64",
    "linux-arm64",
    "darwin-arm64",
    "windows-amd64",
    "windows-arm64",
)
TOOLS = {
    "azureKubelogin": {
        "command": "kubelogin",
        "version": "0.2.19",
        "number": 50,
        "label": "azure-kubelogin",
    },
    "cue": {"command": "cue", "version": "0.17.1", "number": 51, "label": "cue"},
    "helm": {
        "command": "helm",
        "version": "4.2.4",
        "number": 52,
        "label": "helm",
    },
    "kubectl": {
        "command": "kubectl",
        "version": "1.37.0",
        "number": 53,
        "label": "kubectl",
    },
    "kustomize": {
        "command": "kustomize",
        "version": "5.8.1",
        "number": 54,
        "label": "kustomize",
    },
}
BASH = shutil.which("bash")
PWSH = shutil.which("pwsh")


def _load_data() -> dict:
    return tomllib.loads(DATA_PATH.read_text(encoding="utf-8"))


def _script_path(spec: dict, suffix: str) -> pathlib.Path:
    return SOURCE_ROOT / (
        f"run_after_{spec['number']}-install-{spec['label']}.{suffix}.tmpl"
    )


def _render(path: pathlib.Path, os_name: str, arch: str, data: dict | None = None) -> str:
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
    result = execute_template(path=path, data=override, source_root=SOURCE_ROOT)
    if result.returncode != 0:
        raise AssertionError(f"{path.name} failed to render: {result.stderr}")
    return result.stdout


def _write_executable(path: pathlib.Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("utf-8"))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _binary_body(command: str, version: str, *, exit_code: int = 0) -> str:
    probes = {
        "kubelogin": (
            '[ "$#" -eq 1 ] && [ "$1" = "--version" ] || exit 64\n'
            f"printf '%s\\n' 'git hash: v{version}/synthetic' 'Go version: synthetic'\n"
        ),
        "cue": (
            '[ "$#" -eq 1 ] && [ "$1" = "version" ] || exit 64\n'
            f"printf '%s\\n' 'cue version v{version}'\n"
        ),
        "helm": (
            '[ "$#" -eq 3 ] && [ "$1" = "version" ] && '
            '[ "$2" = "--template" ] && [ "$3" = "{{.Version}}" ] || exit 64\n'
            f"printf '%s' 'v{version}'\n"
        ),
        "kubectl": (
            '[ "$#" -eq 3 ] && [ "$1" = "version" ] && '
            '[ "$2" = "--client=true" ] && [ "$3" = "--output=json" ] || exit 64\n'
            f"printf '%s\\n' '{{\"clientVersion\":{{\"gitVersion\":\"v{version}\"}}}}'\n"
        ),
        "kustomize": (
            '[ "$#" -eq 1 ] && [ "$1" = "version" ] || exit 64\n'
            f"printf '%s\\n' 'v{version}'\n"
        ),
    }
    return (
        "#!/bin/sh\n"
        'printf "%s\\n" "$PWD" >> "${PROBE_CWDS:?}"\n'
        + probes[command]
        + f"exit {exit_code}\n"
    )


def _make_archive(archive: str, entry: str, body: str) -> bytes:
    payload = body.encode("utf-8")
    if archive == "raw":
        return payload
    output = io.BytesIO()
    if archive == "zip":
        with zipfile.ZipFile(output, "w") as bundle:
            info = zipfile.ZipInfo(entry)
            info.external_attr = 0o755 << 16
            bundle.writestr(info, payload)
    elif archive == "tar.gz":
        with tarfile.open(fileobj=output, mode="w:gz") as bundle:
            info = tarfile.TarInfo(entry)
            info.mode = 0o755
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))
    else:
        raise AssertionError(f"unexpected archive type: {archive}")
    return output.getvalue()


def _make_symlink_archive(archive: str, entry: str) -> bytes:
    output = io.BytesIO()
    if archive == "zip":
        with zipfile.ZipFile(output, "w") as bundle:
            info = zipfile.ZipInfo(entry)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(info, "elsewhere")
    elif archive == "tar.gz":
        with tarfile.open(fileobj=output, mode="w:gz") as bundle:
            info = tarfile.TarInfo(entry)
            info.type = tarfile.SYMTYPE
            info.linkname = "elsewhere"
            bundle.addfile(info)
    else:
        raise AssertionError(f"unexpected symlink archive type: {archive}")
    return output.getvalue()


def _elf_header(machine: int) -> bytes:
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    header[18:20] = struct.pack("<H", machine)
    return bytes(header)


def _mach_o_header(cpu_type: int) -> bytes:
    return b"\xcf\xfa\xed\xfe" + struct.pack("<I", cpu_type) + bytes(56)


def _pe_header(machine: int) -> bytes:
    header = bytearray(128)
    header[:2] = b"MZ"
    header[0x3C:0x40] = struct.pack("<I", 0x40)
    header[0x40:0x44] = b"PE\0\0"
    header[0x44:0x46] = struct.pack("<H", machine)
    return bytes(header)


def _extract_between(source: str, start: str, end: str) -> str:
    return source[source.index(start) : source.index(end)]


class DeclarationAndRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _load_data()

    def test_declarations_are_exact_native_assets(self) -> None:
        expected_keys = {
            "file", "url", "sha256", "archive", "entry", "executableArch", "emulated"
        }
        for data_name, spec in TOOLS.items():
            tool = self.data[data_name]
            with self.subTest(tool=data_name):
                self.assertEqual(tool["version"], spec["version"])
                self.assertEqual(set(tool["assets"]), set(PLATFORMS))
            for platform, asset in tool["assets"].items():
                with self.subTest(tool=data_name, platform=platform):
                    self.assertEqual(set(asset), expected_keys)
                    self.assertTrue(asset["url"].startswith("https://"), asset["url"])
                    self.assertIn(spec["version"], asset["url"])
                    self.assertRegex(asset["sha256"], r"^[0-9a-f]{64}$")
                    self.assertIn(asset["archive"], {"raw", "zip", "tar.gz"})
                    self.assertFalse(asset["emulated"])
                    self.assertEqual(
                        asset["executableArch"], platform.rsplit("-", maxsplit=1)[1]
                    )
                    if asset["archive"] == "raw":
                        self.assertEqual(asset["entry"], "")
                    else:
                        self.assertNotEqual(asset["entry"], "")

    def test_all_five_platforms_render_the_declared_assets(self) -> None:
        for data_name, spec in TOOLS.items():
            for platform in PLATFORMS:
                os_name, arch = platform.split("-", maxsplit=1)
                suffix = "ps1" if os_name == "windows" else "sh"
                rendered = _render(_script_path(spec, suffix), os_name, arch)
                asset = self.data[data_name]["assets"][platform]
                with self.subTest(tool=data_name, platform=platform):
                    self.assertIn(asset["url"], rendered)
                    self.assertIn(asset["sha256"], rendered)
                    self.assertIn(asset["file"], rendered)
                    self.assertNotIn("has no asset", rendered)

    @unittest.skipUnless(BASH, "bash is required for POSIX syntax checks")
    def test_rendered_posix_scripts_pass_bash_n(self) -> None:
        for spec in TOOLS.values():
            for platform in ("linux-amd64", "linux-arm64", "darwin-arm64"):
                os_name, arch = platform.split("-", maxsplit=1)
                rendered = _render(_script_path(spec, "sh"), os_name, arch)
                with self.subTest(tool=spec["command"], platform=platform):
                    result = subprocess.run(
                        [BASH, "-n"],
                        input=rendered,
                        capture_output=True,
                        encoding="utf-8",
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_windows_directory_rejection_precedes_mise_link_acceptance(self) -> None:
        for spec in TOOLS.values():
            with self.subTest(tool=spec["command"]):
                rendered = _render(_script_path(spec, "ps1"), "windows", "amd64")
                guard = _extract_between(
                    rendered,
                    "function Assert-TargetReplaceable",
                    "function Test-BinaryArchitecture",
                )
                self.assertLess(guard.index("$item.PSIsContainer"), guard.index("::ReparsePoint"))
                self.assertIn("-ErrorVariable cleanupErrors", rendered)
                self.assertIn('Write-Warning "could not remove staging directory', rendered)

    def test_probe_argv_and_transaction_guards_are_explicit(self) -> None:
        expected_posix = {
            "kubelogin": '"${binary}" --version',
            "cue": '"${binary}" version',
            "helm": '"${binary}" version --template "${helm_template}"',
            "kubectl": '"${binary}" version --client=true --output=json',
            "kustomize": '"${binary}" version',
        }
        for spec in TOOLS.values():
            sh_source = _render(_script_path(spec, "sh"), "linux", "amd64")
            ps_source = _render(_script_path(spec, "ps1"), "windows", "amd64")
            with self.subTest(tool=spec["command"]):
                self.assertIn(expected_posix[spec["command"]], sh_source)
                self.assertLess(
                    sh_source.index("assert_target_replaceable"),
                    sh_source.index("has_expected_version"),
                )
                self.assertIn('stage_dir="$(mktemp -d "${bin_dir}/.', sh_source)
                self.assertIn('[ -L "${candidate}" ]', sh_source)
                self.assertIn("has_expected_architecture", sh_source)
                self.assertIn(
                    'has_expected_architecture "${target}" &&\n'
                    '  has_expected_version "${target}"',
                    sh_source,
                )
                self.assertIn('mv -f "${candidate}" "${target}"', sh_source)
                self.assertNotIn('rm -f "${target}"', sh_source)
                self.assertIn(
                    "$miseTarget = Join-Path $env:LOCALAPPDATA 'mise\\shims\\",
                    ps_source,
                )
                self.assertNotIn(
                    "$miseTarget = Join-Path $HOME '.local\\share\\mise\\shims",
                    ps_source,
                )
                self.assertIn("ConvertTo-NormalizedPath", ps_source)
                self.assertIn(".Replace('\\', '/')", ps_source)
                self.assertIn("if ($current -ine $expected)", ps_source)
                self.assertIn("function Test-BinaryArchitecture", ps_source)
                self.assertIn("function Assert-TargetReplaceable", ps_source)
                self.assertIn(
                    "$targetState -eq 'File' -and (Test-BinaryArchitecture -Path $target)",
                    ps_source,
                )
                architecture_function = _extract_between(
                    ps_source,
                    "function Test-BinaryArchitecture",
                    "function Test-ExpectedVersion",
                )
                version_start = ps_source.index("function Test-ExpectedVersion")
                version_end_candidates = [
                    index
                    for marker in (
                        "function Assert-ZipEntriesSafe",
                        "function Assert-Unlocked",
                    )
                    if (index := ps_source.find(marker, version_start + 1)) != -1
                ]
                version_function = ps_source[version_start : min(version_end_candidates)]
                self.assertNotIn("catch {\n        return $false", architecture_function)
                self.assertNotIn("catch {\n        return $false", version_function)
                self.assertIn("catch [System.IO.IOException]", architecture_function)
                self.assertIn(
                    "catch [System.Management.Automation.ApplicationFailedException]",
                    version_function,
                )
                self.assertIn("[System.IO.FileShare]::None", ps_source)
                self.assertIn("[System.IO.File]::Move($candidate, $target, $true)", ps_source)
                self.assertNotIn("Remove-Item -LiteralPath $target", ps_source)
                if spec["command"] != "kubectl":
                    self.assertIn("function Assert-ZipEntriesSafe", ps_source)
                    self.assertLess(
                        ps_source.index("Assert-ZipEntriesSafe -Archive $archive"),
                        ps_source.index("Expand-Archive -LiteralPath $archive"),
                    )
        helm = _render(_script_path(TOOLS["helm"], "sh"), "linux", "amd64")
        self.assertIn("helm_template='{{.Version}}'", helm)
        kubectl = _render(_script_path(TOOLS["kubectl"], "ps1"), "windows", "amd64")
        self.assertLess(
            kubectl.index("$LASTEXITCODE -ne 0"),
            kubectl.index("ConvertFrom-Json"),
        )

    @unittest.skipUnless(PWSH, "pwsh is unavailable; Windows parser checks skipped")
    def test_rendered_windows_scripts_parse(self) -> None:
        for spec in TOOLS.values():
            rendered = _render(_script_path(spec, "ps1"), "windows", "amd64")
            with tempfile.TemporaryDirectory() as temp:
                path = pathlib.Path(temp) / "installer.ps1"
                path.write_text(rendered, encoding="utf-8", newline="\n")
                command = (
                    "$errors=$null; "
                    "[System.Management.Automation.Language.Parser]::ParseFile("
                    f"'{str(path).replace(chr(39), chr(39) * 2)}',"
                    "[ref]$null,[ref]$errors) | Out-Null; "
                    "if ($errors.Count) { $errors | ForEach-Object { $_.Message }; exit 1 }"
                )
                result = subprocess.run(
                    [PWSH, "-NoProfile", "-Command", command],
                    capture_output=True,
                    encoding="utf-8",
                    check=False,
                )
                with self.subTest(tool=spec["command"]):
                    self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    @unittest.skipUnless(BASH, "bash is required for POSIX architecture checks")
    def test_posix_binary_header_parser_accepts_only_the_rendered_architecture(
        self,
    ) -> None:
        source = _render(_script_path(TOOLS["cue"], "sh"), "linux", "amd64")
        function = _extract_between(
            source, "has_expected_architecture() {", "has_expected_version() {"
        )
        cases = (
            ("linux", "amd64", _elf_header(0x3E), True),
            ("linux", "amd64", _elf_header(0xB7), False),
            ("linux", "arm64", _elf_header(0xB7), True),
            ("linux", "arm64", b"not-an-elf", False),
            ("darwin", "arm64", _mach_o_header(0x0100000C), True),
            ("darwin", "arm64", _mach_o_header(0x01000007), False),
            ("darwin", "arm64", b"not-a-mach-o", False),
        )
        for os_name, arch, payload, expected in cases:
            with self.subTest(os=os_name, arch=arch, expected=expected):
                with tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    binary = root / "candidate"
                    binary.write_bytes(payload)
                    checker = root / "check.sh"
                    _write_executable(
                        checker,
                        "#!/usr/bin/env bash\n"
                        "set -euo pipefail\n"
                        f"platform_os={os_name!r}\n"
                        f"platform_arch={arch!r}\n"
                        + function
                        + '\nhas_expected_architecture "$1"\n',
                    )
                    result = subprocess.run(
                        [BASH, str(checker), str(binary)],
                        capture_output=True,
                        encoding="utf-8",
                        check=False,
                    )
                    self.assertEqual(result.returncode == 0, expected, result.stderr)

    @unittest.skipUnless(PWSH, "pwsh is unavailable; PE header checks skipped")
    def test_windows_pe_header_parser_accepts_only_the_rendered_architecture(
        self,
    ) -> None:
        source = _render(_script_path(TOOLS["cue"], "ps1"), "windows", "amd64")
        function = _extract_between(
            source, "function Test-BinaryArchitecture", "function Test-ExpectedVersion"
        )
        cases = (
            ("amd64", _pe_header(0x8664), True),
            ("amd64", _pe_header(0xAA64), False),
            ("arm64", _pe_header(0xAA64), True),
            ("arm64", b"not-a-pe", False),
        )
        for arch, payload, expected in cases:
            with self.subTest(arch=arch, expected=expected):
                with tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    binary = root / "candidate.exe"
                    binary.write_bytes(payload)
                    checker = root / "check.ps1"
                    quoted = str(binary).replace("'", "''")
                    checker.write_text(
                        f"$platformArch = '{arch}'\n"
                        + function
                        + f"\nif (Test-BinaryArchitecture -Path '{quoted}') {{ exit 0 }}"
                        " else { exit 1 }\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    result = subprocess.run(
                        [PWSH, "-NoProfile", "-File", str(checker)],
                        capture_output=True,
                        encoding="utf-8",
                        check=False,
                    )
                    self.assertEqual(result.returncode == 0, expected, result.stderr)


@unittest.skipIf(os.name == "nt", "POSIX behavior is not tested through Git Bash")
@unittest.skipUnless(BASH, "bash is required for POSIX behavior tests")
class PosixInstallBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _load_data()

    def _fixture(
        self,
        root: pathlib.Path,
        data_name: str,
        *,
        exit_code: int = 0,
        missing_entry: bool = False,
    ) -> tuple[pathlib.Path, dict]:
        spec = TOOLS[data_name]
        declared = self.data[data_name]["assets"]["linux-amd64"]
        entry = declared["entry"]
        archive_entry = f"missing/{spec['command']}" if missing_entry else entry
        body = _binary_body(spec["command"], spec["version"], exit_code=exit_code)
        payload = _make_archive(declared["archive"], archive_entry, body)
        fixture = root / declared["file"]
        fixture.write_bytes(payload)
        asset = dict(declared)
        asset["sha256"] = hashlib.sha256(payload).hexdigest()
        override = {
            data_name: {
                "version": spec["version"],
                "assets": {"linux-amd64": asset},
            }
        }
        return fixture, override

    def _prepare(
        self,
        root: pathlib.Path,
        data_name: str,
        *,
        fixture: pathlib.Path | None,
        override: dict,
        curl_fail: bool = False,
        mv_fail: bool = False,
    ) -> tuple[pathlib.Path, pathlib.Path, dict[str, str]]:
        spec = TOOLS[data_name]
        home = root / "home"
        bin_dir = home / ".local/bin"
        stub_dir = root / "stubs"
        bin_dir.mkdir(parents=True)
        stub_dir.mkdir()
        calls = root / "curl-calls"
        probe_cwds = root / "probe-cwds"
        curl_body = """#!/bin/sh
printf 'called\n' >> "$STUB_CURL_CALLS"
[ "${STUB_CURL_FAIL:-0}" = 0 ] || exit 22
output=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) output="$2"; shift 2 ;;
    *) shift ;;
  esac
done
cp "$STUB_CURL_SOURCE" "$output"
"""
        _write_executable(stub_dir / "curl", curl_body)
        _write_executable(
            stub_dir / "od",
            "#!/bin/sh\n"
            "printf '%s\\n' "
            "' 7f 45 4c 46 02 01 01 00 00 00 00 00 00 00 00 00 02 00 3e 00'\n",
        )
        if mv_fail:
            _write_executable(stub_dir / "mv", "#!/bin/sh\nexit 73\n")
        if spec["command"] == "kubectl":
            _write_executable(
                bin_dir / "jq",
                "#!/bin/sh\n"
                "input=$(cat)\n"
                "case \"$input\" in\n"
                "  *'\"gitVersion\":\"v1.37.0\"'*) printf '%s\\n' 'v1.37.0' ;;\n"
                "  *) exit 1 ;;\n"
                "esac\n",
            )
        rendered = _render(
            _script_path(spec, "sh"), "linux", "amd64", data=override
        )
        script = root / "installer.sh"
        _write_executable(script, rendered)
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "PATH": f"{stub_dir}{os.pathsep}{env['PATH']}",
                "STUB_CURL_CALLS": str(calls),
                "STUB_CURL_FAIL": "1" if curl_fail else "0",
                "STUB_CURL_SOURCE": str(fixture or root / "unused"),
                "PROBE_CWDS": str(probe_cwds),
            }
        )
        return script, home, env

    def _run(
        self,
        root: pathlib.Path,
        data_name: str,
        *,
        fixture: pathlib.Path | None,
        override: dict,
        curl_fail: bool = False,
        mv_fail: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], pathlib.Path, pathlib.Path]:
        script, home, env = self._prepare(
            root,
            data_name,
            fixture=fixture,
            override=override,
            curl_fail=curl_fail,
            mv_fail=mv_fail,
        )
        result = subprocess.run(
            [BASH, str(script)],
            env=env,
            cwd=root,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        return result, home, pathlib.Path(env["STUB_CURL_CALLS"])

    def test_fresh_install_and_local_fast_path_for_all_tools(self) -> None:
        for data_name, spec in TOOLS.items():
            with self.subTest(tool=spec["command"]):
                with tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    fixture, override = self._fixture(root, data_name)
                    script, home, env = self._prepare(
                        root, data_name, fixture=fixture, override=override
                    )
                    target = home / ".local/bin" / spec["command"]
                    sentinel = home / ".local/bin/foreign.keep"
                    sentinel.write_text("keep", encoding="utf-8")
                    result = subprocess.run(
                        [BASH, str(script)],
                        env=env,
                        cwd=root,
                        capture_output=True,
                        encoding="utf-8",
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(target.is_file())
                    self.assertFalse(target.is_symlink())
                    calls = pathlib.Path(env["STUB_CURL_CALLS"])
                    self.assertEqual(calls.read_text(encoding="utf-8"), "called\n")

                    calls.unlink()
                    env["STUB_CURL_FAIL"] = "1"
                    second = subprocess.run(
                        [BASH, str(script)],
                        env=env,
                        cwd=root,
                        capture_output=True,
                        encoding="utf-8",
                        check=False,
                    )
                    self.assertEqual(second.returncode, 0, second.stderr)
                    self.assertFalse(calls.exists())
                    self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
                    probe_cwds = pathlib.Path(env["PROBE_CWDS"]).read_text(
                        encoding="utf-8"
                    ).splitlines()
                    self.assertEqual(probe_cwds[-1], str(home / ".local/bin"))

    def test_regular_old_tool_at_the_declared_name_can_be_upgraded(self) -> None:
        for data_name, spec in TOOLS.items():
            with self.subTest(tool=spec["command"]):
                with tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    fixture, override = self._fixture(root, data_name)
                    script, home, env = self._prepare(
                        root, data_name, fixture=fixture, override=override
                    )
                    target = home / ".local/bin" / spec["command"]
                    _write_executable(
                        target, _binary_body(spec["command"], "0.0.1")
                    )
                    old_bytes = target.read_bytes()
                    result = subprocess.run(
                        [BASH, str(script)],
                        env=env,
                        cwd=root,
                        capture_output=True,
                        encoding="utf-8",
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertNotEqual(target.read_bytes(), old_bytes)

    def test_failures_are_nonzero_and_preserve_existing_target(self) -> None:
        cases = ("download", "checksum", "version", "version-exit", "rename")
        for data_name, spec in TOOLS.items():
            for failure in cases:
                with self.subTest(tool=spec["command"], failure=failure):
                    with tempfile.TemporaryDirectory() as temp:
                        root = pathlib.Path(temp)
                        fixture, override = self._fixture(
                            root,
                            data_name,
                            exit_code=1 if failure == "version-exit" else 0,
                        )
                        if failure == "version":
                            fixture, override = self._fixture(root, data_name)
                            fixture.write_bytes(
                                _make_archive(
                                    self.data[data_name]["assets"]["linux-amd64"][
                                        "archive"
                                    ],
                                    self.data[data_name]["assets"]["linux-amd64"][
                                        "entry"
                                    ],
                                    _binary_body(spec["command"], "9.9.9"),
                                )
                            )
                            override[data_name]["assets"]["linux-amd64"]["sha256"] = (
                                hashlib.sha256(fixture.read_bytes()).hexdigest()
                            )
                        if failure == "checksum":
                            override[data_name]["assets"]["linux-amd64"]["sha256"] = (
                                "0" * 64
                            )
                        script, home, env = self._prepare(
                            root,
                            data_name,
                            fixture=fixture,
                            override=override,
                            curl_fail=failure == "download",
                            mv_fail=failure == "rename",
                        )
                        target = home / ".local/bin" / spec["command"]
                        target.write_text("old bytes", encoding="utf-8")
                        result = subprocess.run(
                            [BASH, str(script)],
                            env=env,
                            cwd=root,
                            capture_output=True,
                            encoding="utf-8",
                            check=False,
                        )
                        self.assertNotEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(target.read_text(encoding="utf-8"), "old bytes")

    def test_wrong_candidate_architecture_is_not_executed_or_published(self) -> None:
        for data_name, spec in TOOLS.items():
            with self.subTest(tool=spec["command"]):
                with tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    fixture, override = self._fixture(root, data_name)
                    script, home, env = self._prepare(
                        root, data_name, fixture=fixture, override=override
                    )
                    _write_executable(
                        root / "stubs/od",
                        "#!/bin/sh\n"
                        "printf '%s\\n' "
                        "' 7f 45 4c 46 02 01 01 00 00 00 00 00 00 00 00 00"
                        " 02 00 b7 00'\n",
                    )
                    target = home / ".local/bin" / spec["command"]
                    target.write_text("old bytes", encoding="utf-8")
                    result = subprocess.run(
                        [BASH, str(script)],
                        env=env,
                        cwd=root,
                        capture_output=True,
                        encoding="utf-8",
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(target.read_text(encoding="utf-8"), "old bytes")
                    self.assertFalse(pathlib.Path(env["PROBE_CWDS"]).exists())

    def test_wrong_local_architecture_is_not_treated_as_compliant(self) -> None:
        for data_name, spec in TOOLS.items():
            with self.subTest(tool=spec["command"]):
                with tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    fixture, override = self._fixture(root, data_name)
                    script, home, env = self._prepare(
                        root,
                        data_name,
                        fixture=fixture,
                        override=override,
                        curl_fail=True,
                    )
                    _write_executable(
                        root / "stubs/od",
                        "#!/bin/sh\n"
                        "printf '%s\\n' "
                        "' 7f 45 4c 46 02 01 01 00 00 00 00 00 00 00 00 00"
                        " 02 00 b7 00'\n",
                    )
                    target = home / ".local/bin" / spec["command"]
                    _write_executable(
                        target, _binary_body(spec["command"], spec["version"])
                    )
                    old_bytes = target.read_bytes()
                    result = subprocess.run(
                        [BASH, str(script)],
                        env=env,
                        cwd=root,
                        capture_output=True,
                        encoding="utf-8",
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(target.read_bytes(), old_bytes)
                    self.assertEqual(
                        pathlib.Path(env["STUB_CURL_CALLS"]).read_text(encoding="utf-8"),
                        "called\n",
                    )
                    self.assertFalse(pathlib.Path(env["PROBE_CWDS"]).exists())

    def test_declared_executable_architecture_must_match_the_platform(self) -> None:
        for data_name, spec in TOOLS.items():
            with self.subTest(tool=spec["command"]):
                with tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    fixture, override = self._fixture(root, data_name)
                    override[data_name]["assets"]["linux-amd64"][
                        "executableArch"
                    ] = "arm64"
                    result, home, calls = self._run(
                        root, data_name, fixture=fixture, override=override
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(calls.exists())
                    self.assertFalse(
                        (home / ".local/bin" / spec["command"]).exists()
                    )

    def test_missing_archive_entry_is_nonzero_and_preserves_existing(self) -> None:
        for data_name, spec in TOOLS.items():
            archive = self.data[data_name]["assets"]["linux-amd64"]["archive"]
            if archive == "raw":
                continue
            with self.subTest(tool=spec["command"]):
                with tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    fixture, override = self._fixture(
                        root, data_name, missing_entry=True
                    )
                    script, home, env = self._prepare(
                        root, data_name, fixture=fixture, override=override
                    )
                    target = home / ".local/bin" / spec["command"]
                    target.write_text("old bytes", encoding="utf-8")
                    result = subprocess.run(
                        [BASH, str(script)],
                        env=env,
                        cwd=root,
                        capture_output=True,
                        encoding="utf-8",
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(target.read_text(encoding="utf-8"), "old bytes")

    def test_archive_symlink_entry_is_rejected(self) -> None:
        for data_name in ("azureKubelogin", "cue"):
            spec = TOOLS[data_name]
            with self.subTest(tool=spec["command"]):
                with tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    declared = self.data[data_name]["assets"]["linux-amd64"]
                    payload = _make_symlink_archive(
                        declared["archive"], declared["entry"]
                    )
                    fixture = root / declared["file"]
                    fixture.write_bytes(payload)
                    asset = dict(declared)
                    asset["sha256"] = hashlib.sha256(payload).hexdigest()
                    override = {
                        data_name: {
                            "version": spec["version"],
                            "assets": {"linux-amd64": asset},
                        }
                    }
                    result, home, _ = self._run(
                        root, data_name, fixture=fixture, override=override
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(
                        (home / ".local/bin" / spec["command"]).exists()
                    )

    def test_fresh_download_failure_leaves_no_target(self) -> None:
        for data_name, spec in TOOLS.items():
            with self.subTest(tool=spec["command"]):
                with tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    fixture, override = self._fixture(root, data_name)
                    result, home, _ = self._run(
                        root,
                        data_name,
                        fixture=fixture,
                        override=override,
                        curl_fail=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse((home / ".local/bin" / spec["command"]).exists())

    def test_foreign_symlinks_and_directories_are_rejected_before_network(self) -> None:
        for data_name, spec in TOOLS.items():
            for kind in ("symlink", "directory"):
                with self.subTest(tool=spec["command"], kind=kind):
                    with tempfile.TemporaryDirectory() as temp:
                        root = pathlib.Path(temp)
                        fixture, override = self._fixture(root, data_name)
                        script, home, env = self._prepare(
                            root, data_name, fixture=fixture, override=override
                        )
                        target = home / ".local/bin" / spec["command"]
                        if kind == "symlink":
                            target.symlink_to(root / "foreign")
                        else:
                            target.mkdir()
                        result = subprocess.run(
                            [BASH, str(script)],
                            env=env,
                            cwd=root,
                            capture_output=True,
                            encoding="utf-8",
                            check=False,
                        )
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse(pathlib.Path(env["STUB_CURL_CALLS"]).exists())
                        if kind == "symlink":
                            self.assertTrue(target.is_symlink())
                        else:
                            self.assertTrue(target.is_dir())

    def test_stale_mise_symlink_is_replaced_without_invoking_it(self) -> None:
        for data_name, spec in TOOLS.items():
            for shim_state in ("file", "dangling"):
                with self.subTest(tool=spec["command"], shim_state=shim_state):
                    with tempfile.TemporaryDirectory() as temp:
                        root = pathlib.Path(temp)
                        fixture, override = self._fixture(root, data_name)
                        script, home, env = self._prepare(
                            root, data_name, fixture=fixture, override=override
                        )
                        shim = home / ".local/share/mise/shims" / spec["command"]
                        invoked = root / "old-mise-invoked"
                        if shim_state == "file":
                            _write_executable(
                                shim,
                                "#!/bin/sh\n"
                                f"touch '{invoked}'\n"
                                + _binary_body(spec["command"], spec["version"]),
                            )
                        else:
                            shim.parent.mkdir(parents=True)
                        target = home / ".local/bin" / spec["command"]
                        target.symlink_to(shim)
                        result = subprocess.run(
                            [BASH, str(script)],
                            env=env,
                            cwd=root,
                            capture_output=True,
                            encoding="utf-8",
                            check=False,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertTrue(target.is_file())
                        self.assertFalse(target.is_symlink())
                        self.assertFalse(invoked.exists())

    def test_mise_symlink_to_directory_is_rejected_before_network(self) -> None:
        for data_name, spec in TOOLS.items():
            with self.subTest(tool=spec["command"]):
                with tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    fixture, override = self._fixture(root, data_name)
                    script, home, env = self._prepare(
                        root, data_name, fixture=fixture, override=override
                    )
                    shim = home / ".local/share/mise/shims" / spec["command"]
                    shim.mkdir(parents=True)
                    marker = shim / "keep"
                    marker.write_text("old directory", encoding="utf-8")
                    target = home / ".local/bin" / spec["command"]
                    target.symlink_to(shim, target_is_directory=True)

                    result = subprocess.run(
                        [BASH, str(script)],
                        env=env,
                        cwd=root,
                        capture_output=True,
                        encoding="utf-8",
                        check=False,
                    )

                    self.assertNotEqual(result.returncode, 0)
                    self.assertTrue(target.is_symlink())
                    self.assertTrue(shim.is_dir())
                    self.assertEqual(marker.read_text(encoding="utf-8"), "old directory")
                    self.assertFalse(pathlib.Path(env["STUB_CURL_CALLS"]).exists())
                    self.assertFalse((shim / spec["command"]).exists())

    def test_owned_staging_is_cleaned_without_touching_foreign_files(self) -> None:
        for data_name, spec in TOOLS.items():
            with self.subTest(tool=spec["command"]):
                with tempfile.TemporaryDirectory() as temp:
                    root = pathlib.Path(temp)
                    fixture, override = self._fixture(root, data_name)
                    script, home, env = self._prepare(
                        root, data_name, fixture=fixture, override=override, curl_fail=True
                    )
                    foreign = home / ".local/bin" / f".{spec['command']}-install.keep"
                    foreign.write_text("keep", encoding="utf-8")
                    result = subprocess.run(
                        [BASH, str(script)],
                        env=env,
                        cwd=root,
                        capture_output=True,
                        encoding="utf-8",
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(foreign.read_text(encoding="utf-8"), "keep")
                    leftovers = list(
                        (home / ".local/bin").glob(f".{spec['command']}-install.??????")
                    )
                    self.assertEqual(leftovers, [])


@unittest.skipUnless(
    os.name == "nt" and PWSH,
    "Windows-only lock behavior requires native PowerShell",
)
class WindowsLockBehaviourTests(unittest.TestCase):
    def test_mise_link_comparison_normalizes_slashes_and_case(self) -> None:
        spec = TOOLS["cue"]
        rendered = _render(_script_path(spec, "ps1"), "windows", "amd64")
        functions = _extract_between(
            rendered,
            "function ConvertTo-NormalizedPath",
            "function Test-BinaryArchitecture",
        )
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            script = root / "mise-link-test.ps1"
            script.write_text(
                "$target = 'C:\\Users\\Example\\.local\\bin\\cue.exe'\n"
                "$miseTarget = 'C:\\Users\\Example\\AppData\\Local\\mise\\shims\\cue.exe'\n"
                + functions
                + "\nfunction Get-Item {\n"
                "  [pscustomobject]@{\n"
                "    Attributes = [System.IO.FileAttributes]::ReparsePoint\n"
                "    Target = 'c:/users/example/appdata/local/MISE/shims/CUE.exe'\n"
                "    DirectoryName = 'C:\\Users\\Example\\.local\\bin'\n"
                "  }\n"
                "}\n"
                "if ((Assert-TargetReplaceable) -ne 'MiseLink') { exit 81 }\n"
                "Remove-Item Function:Get-Item\n"
                "function Get-Item {\n"
                "  [pscustomobject]@{\n"
                "    Attributes = [System.IO.FileAttributes]::ReparsePoint\n"
                "    Target = 'C:/foreign/cue.exe'\n"
                "    DirectoryName = 'C:\\Users\\Example\\.local\\bin'\n"
                "  }\n"
                "}\n"
                "$rejected = $false\n"
                "try { Assert-TargetReplaceable } catch { $rejected = $true }\n"
                "if (-not $rejected) { exit 82 }\n"
                "Remove-Item Function:Get-Item\n"
                "function Get-Item {\n"
                "  [pscustomobject]@{\n"
                "    PSIsContainer = $true\n"
                "    Attributes = [System.IO.FileAttributes]::ReparsePoint -bor [System.IO.FileAttributes]::Directory\n"
                "    Target = $miseTarget\n"
                "    DirectoryName = 'C:\\Users\\Example\\.local\\bin'\n"
                "  }\n"
                "}\n"
                "try { Assert-TargetReplaceable; exit 83 } catch { exit 0 }\n",
                encoding="utf-8",
                newline="\n",
            )
            result = subprocess.run(
                [PWSH, "-NoProfile", "-File", str(script)],
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_locked_target_fails_before_bytes_change(self) -> None:
        spec = TOOLS["cue"]
        rendered = _render(_script_path(spec, "ps1"), "windows", "amd64")
        functions = rendered[
            rendered.index("function Assert-TargetReplaceable") :
            rendered.index("$targetState = Assert-TargetReplaceable")
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            target = root / "cue.exe"
            target.write_bytes(b"old bytes")
            script = root / "lock-test.ps1"
            quoted_target = str(target).replace("'", "''")
            quoted_mise = str(root / "mise/cue.exe").replace("'", "''")
            script.write_text(
                "$ErrorActionPreference = 'Stop'\n"
                f"$target = '{quoted_target}'\n"
                f"$miseTarget = '{quoted_mise}'\n"
                + functions
                + "\n$lock = [System.IO.File]::Open("
                "$target,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,"
                "[System.IO.FileShare]::Read)\n"
                "try {\n"
                "  try { Assert-Unlocked; exit 91 } catch { exit 0 }\n"
                "} finally { $lock.Dispose() }\n",
                encoding="utf-8",
                newline="\n",
            )
            result = subprocess.run(
                [PWSH, "-NoProfile", "-File", str(script)],
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(target.read_bytes(), b"old bytes")


if __name__ == "__main__":
    unittest.main()
