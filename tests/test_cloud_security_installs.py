"""P2 security/cloud tools の直接導入と Terraform 署名検証を検証する。"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import pathlib
import shutil
import stat
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
PACKAGE_INSTALL = SOURCE_ROOT / "run_once_before_10-install-packages.sh.tmpl"
BASH = shutil.which("bash")
PWSH = shutil.which("pwsh")
GPG = shutil.which("gpg")

PLATFORMS = (
    "linux-amd64",
    "linux-arm64",
    "darwin-arm64",
    "windows-amd64",
    "windows-arm64",
)
TOOLS = {
    "cosign": {"number": 55, "archive": "raw"},
    "sqlc": {"number": 56, "archive": "tar.gz"},
    "trivy": {"number": 58, "archive": "tar.gz"},
    "yq": {"number": 59, "archive": "raw"},
}


def _load_data() -> dict:
    return tomllib.loads(DATA_PATH.read_text(encoding="utf-8"))


def _script(tool: str, suffix: str) -> pathlib.Path:
    number = 57 if tool == "terraform" else TOOLS[tool]["number"]
    return SOURCE_ROOT / f"run_after_{number}-install-{tool}.{suffix}.tmpl"


def _render(
    path: pathlib.Path, os_name: str, arch: str, data: dict | None = None
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
    result = execute_template(path=path, data=override, source_root=SOURCE_ROOT)
    if result.returncode != 0:
        raise AssertionError(f"{path.name} failed to render: {result.stderr}")
    return result.stdout


def _write_executable(path: pathlib.Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("utf-8"))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive(kind: str, entry: str, body: str) -> bytes:
    payload = body.encode("utf-8")
    if kind == "raw":
        return payload
    output = io.BytesIO()
    if kind == "tar.gz":
        with tarfile.open(fileobj=output, mode="w:gz") as bundle:
            info = tarfile.TarInfo(entry)
            info.mode = 0o755
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))
    elif kind == "zip":
        with zipfile.ZipFile(output, "w") as bundle:
            info = zipfile.ZipInfo(entry)
            info.external_attr = 0o755 << 16
            bundle.writestr(info, payload)
    else:
        raise AssertionError(f"unsupported archive kind {kind}")
    return output.getvalue()


def _binary(
    tool: str, version: str, exit_code: int = 0, header_arch: str = "amd64"
) -> str:
    probes = {
        "cosign": (
            '[ "$#" -eq 2 ] && [ "$1" = "version" ] && [ "$2" = "--json" ] || exit 64\n'
            f"printf '%s\\n' '{{\"gitVersion\":\"v{version}\"}}'\n"
        ),
        "sqlc": (
            '[ "$#" -eq 1 ] && [ "$1" = "version" ] || exit 64\n'
            f"printf '%s\\n' 'v{version}'\n"
        ),
        "trivy": (
            '[ "$#" -eq 3 ] && [ "$1" = "--version" ] && '
            '[ "$2" = "--format" ] && [ "$3" = "json" ] || exit 64\n'
            'test -d "${TRIVY_CACHE_DIR:?}" || exit 65\n'
            'printf "%s|%s\\n" "$PWD" "$TRIVY_CACHE_DIR" >> "${PROBE_LOG:?}"\n'
            f"printf '%s\\n' '{{\"Version\":\"{version}\"}}'\n"
        ),
        "yq": (
            '[ "$#" -eq 1 ] && [ "$1" = "--version" ] || exit 64\n'
            f"printf '%s\\n' 'yq (https://github.com/mikefarah/yq/) version v{version}'\n"
        ),
        "terraform": (
            '[ "$#" -eq 2 ] && [ "$1" = "version" ] && [ "$2" = "-json" ] || exit 64\n'
            '[ "${CHECKPOINT_DISABLE:-}" = 1 ] || exit 65\n'
            '[ -f "${TF_CLI_CONFIG_FILE:?}" ] || exit 66\n'
            'printf "%s|%s\\n" "$PWD" "$TF_CLI_CONFIG_FILE" >> "${PROBE_LOG:?}"\n'
            f"printf '%s\\n' '{{\"terraform_version\":\"{version}\"}}'\n"
        ),
    }
    return (
        "#!/bin/sh\n"
        f"# TEST_EXECUTABLE_ARCH={header_arch}\n"
        + probes[tool]
        + f"exit {exit_code}\n"
    )


def _jq_stub() -> str:
    return """#!/bin/sh
input=$(cat)
case "$input" in
  *'"gitVersion":"v3.1.3"'*) printf '%s\n' 'v3.1.3' ;;
  *'"Version":"0.74.0"'*|*'"version":"0.74.0"'*) printf '%s\n' '0.74.0' ;;
  *'"terraform_version":"1.16.1"'*) printf '%s\n' '1.16.1' ;;
  *) exit 1 ;;
esac
"""


def _curl_stub() -> str:
    return """#!/bin/sh
printf 'called\n' >> "$STUB_CURL_CALLS"
[ "${STUB_CURL_FAIL:-0}" = 0 ] || exit 22
output=""
url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) output="$2"; shift 2 ;;
    http*) url="$1"; shift ;;
    *) shift ;;
  esac
done
[ "${STUB_CURL_FAIL_BASENAME:-}" != "${url##*/}" ] || exit 22
cp "$STUB_DOWNLOAD_DIR/${url##*/}" "$output"
"""


def _od_stub() -> str:
    return """#!/bin/sh
file=""
for argument do file="$argument"; done
case "$(cat "$file" 2>/dev/null)" in
  *TEST_EXECUTABLE_ARCH=amd64*) printf '%s\n' '7f 45 4c 46 02 01 00 00 00 00 00 00 00 00 00 00 02 00 3e 00' ;;
  *TEST_EXECUTABLE_ARCH=arm64*) printf '%s\n' '7f 45 4c 46 02 01 00 00 00 00 00 00 00 00 00 00 02 00 b7 00' ;;
  *) printf '%s\n' '00 00' ;;
esac
"""


def _extract_block(source: str, marker: str) -> str:
    start = source.index(f"# >>> {marker}")
    end = source.index(f"# <<< {marker}")
    return source[start:end]


def _elf_header(machine: int) -> bytes:
    return b"\x7fELF\x02\x01" + (b"\0" * 10) + b"\x02\0" + machine.to_bytes(2, "little")


def _macho_header(cpu_type: int) -> bytes:
    return b"\xcf\xfa\xed\xfe" + cpu_type.to_bytes(4, "little") + (b"\0" * 12)


def _pe_header(machine: int) -> bytes:
    payload = bytearray(0x86)
    payload[0:2] = b"MZ"
    payload[0x3C:0x40] = (0x80).to_bytes(4, "little")
    payload[0x80:0x84] = b"PE\0\0"
    payload[0x84:0x86] = machine.to_bytes(2, "little")
    return bytes(payload)


class DeclarationAndRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _load_data()

    def test_declarations_pin_expected_versions_and_platforms(self) -> None:
        expected = {
            "cosign": "3.1.3",
            "sqlc": "1.31.1",
            "terraform": "1.16.1",
            "trivy": "0.74.0",
            "yq": "4.53.6",
        }
        asset_keys = {
            "file",
            "url",
            "sha256",
            "archive",
            "entry",
            "executableArch",
            "emulated",
        }
        for tool, version in expected.items():
            declaration = self.data[tool]
            with self.subTest(tool=tool):
                self.assertEqual(declaration["version"], version)
                self.assertEqual(set(declaration["assets"]), set(PLATFORMS))
            for platform, asset in declaration["assets"].items():
                with self.subTest(tool=tool, platform=platform):
                    self.assertEqual(set(asset), asset_keys)
                    self.assertRegex(asset["sha256"], r"^[0-9a-f]{64}$")
                    self.assertTrue(asset["url"].startswith("https://"))
                    expected_archive = (
                        "zip"
                        if platform.startswith("windows-")
                        and tool in {"sqlc", "terraform", "trivy"}
                        else TOOLS.get(tool, {"archive": "zip"})["archive"]
                    )
                    self.assertEqual(asset["archive"], expected_archive)
                    self.assertEqual(asset["entry"] == "", expected_archive == "raw")

    def test_only_approved_windows_arm64_assets_are_emulated(self) -> None:
        for tool in ("cosign", "sqlc", "terraform", "trivy", "yq"):
            asset = self.data[tool]["assets"]["windows-arm64"]
            with self.subTest(tool=tool):
                if tool in {"cosign", "trivy"}:
                    self.assertEqual(asset["executableArch"], "amd64")
                    self.assertTrue(asset["emulated"])
                else:
                    self.assertEqual(asset["executableArch"], "arm64")
                    self.assertFalse(asset["emulated"])

    def test_terraform_verification_pins_corrected_metadata(self) -> None:
        verification = self.data["terraform"]["verification"]
        self.assertEqual(
            verification["publicKeySha256"],
            "c2f5bc1163bd8d15a711616b587bcede212d045a5b8b52df01c74095897cd065",
        )
        self.assertEqual(
            verification["checksumsSha256"],
            "1a91605f622087cff05a200bfc3618c26dfb0528472620967842c0322f55bac0",
        )
        self.assertEqual(
            verification["signatureSha256"],
            "d5629208adbe1453865ce75dcbacde915e6f96c832ad4dfdb40966d356c22109",
        )
        self.assertEqual(
            verification["primaryFingerprint"],
            "C874011F0AB405110D02105534365D9472D7468F",
        )
        self.assertEqual(
            verification["signingFingerprint"],
            "374EC75B485913604A831CC7C820C6D5CD27AB87",
        )
        self.assertEqual(
            _sha256(base64.b64decode(verification["publicKeyBase64"])),
            verification["publicKeySha256"],
        )
        self.assertEqual(verification["windowsArm64GpgArch"], "amd64")
        self.assertTrue(verification["windowsArm64GpgEmulated"])

    @unittest.skipUnless(GPG, "gpg is required to inspect the embedded public key")
    def test_embedded_hashicorp_key_contains_pinned_fingerprints(self) -> None:
        verification = self.data["terraform"]["verification"]
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            key = root / "hashicorp.asc"
            home = root / "gnupg"
            key.write_bytes(base64.b64decode(verification["publicKeyBase64"]))
            home.mkdir(mode=0o700)
            result = subprocess.run(
                [
                    GPG,
                    "--no-options",
                    "--homedir",
                    str(home),
                    "--batch",
                    "--no-auto-key-retrieve",
                    "--no-autostart",
                    "--with-colons",
                    "--fingerprint",
                    "--fingerprint",
                    "--import-options",
                    "show-only",
                    "--import",
                    str(key),
                ],
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            fingerprints = [
                line.split(":")[9]
                for line in result.stdout.splitlines()
                if line.startswith("fpr:")
            ]
            self.assertEqual(fingerprints[0], verification["primaryFingerprint"])
            self.assertIn(verification["signingFingerprint"], fingerprints)

    def test_every_platform_renders_only_its_declared_asset(self) -> None:
        for tool in ("cosign", "sqlc", "terraform", "trivy", "yq"):
            for platform in PLATFORMS:
                os_name, arch = platform.split("-", maxsplit=1)
                suffix = "ps1" if os_name == "windows" else "sh"
                rendered = _render(_script(tool, suffix), os_name, arch)
                asset = self.data[tool]["assets"][platform]
                with self.subTest(tool=tool, platform=platform):
                    self.assertIn(asset["url"], rendered)
                    self.assertIn(asset["sha256"], rendered)
                    for other_platform, other in self.data[tool]["assets"].items():
                        if other_platform != platform and other["sha256"] != asset["sha256"]:
                            self.assertNotIn(other["sha256"], rendered)

    @unittest.skipUnless(BASH, "bash is required for POSIX syntax checks")
    def test_rendered_posix_scripts_pass_bash_n(self) -> None:
        for tool in ("cosign", "sqlc", "terraform", "trivy", "yq"):
            for platform in ("linux-amd64", "linux-arm64", "darwin-arm64"):
                os_name, arch = platform.split("-", maxsplit=1)
                result = subprocess.run(
                    [BASH, "-n"],
                    input=_render(_script(tool, "sh"), os_name, arch),
                    capture_output=True,
                    encoding="utf-8",
                    check=False,
                )
                with self.subTest(tool=tool, platform=platform):
                    self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(PWSH, "pwsh is unavailable; Windows parser checks skipped")
    def test_rendered_windows_scripts_parse(self) -> None:
        for tool in ("cosign", "sqlc", "terraform", "trivy", "yq"):
            rendered = _render(_script(tool, "ps1"), "windows", "amd64")
            with tempfile.TemporaryDirectory() as temporary:
                path = pathlib.Path(temporary) / "installer.ps1"
                path.write_text(rendered, encoding="utf-8", newline="\n")
                quoted = str(path).replace("'", "''")
                command = (
                    "$errors=$null;"
                    "[Management.Automation.Language.Parser]::ParseFile("
                    f"'{quoted}',[ref]$null,[ref]$errors)|Out-Null;"
                    "if($errors.Count){$errors|% Message;exit 1}"
                )
                result = subprocess.run(
                    [PWSH, "-NoProfile", "-Command", command],
                    capture_output=True,
                    encoding="utf-8",
                    check=False,
                )
                with self.subTest(tool=tool):
                    self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_transaction_and_probe_guards_are_explicit(self) -> None:
        for tool in ("cosign", "sqlc", "terraform", "trivy", "yq"):
            sh_source = _render(_script(tool, "sh"), "linux", "amd64")
            ps_source = _render(_script(tool, "ps1"), "windows", "amd64")
            with self.subTest(tool=tool):
                self.assertIn(f'.{tool}-install.$$.$index', sh_source)
                self.assertNotIn("mktemp", sh_source)
                self.assertNotIn('rm -f "${target}"', sh_source)
                self.assertIn('[ ! -L "${staged}" ]', sh_source)
                self.assertIn('mv -f "${staged}" "${target}"', sh_source)
                self.assertIn("[IO.FileShare]::None", ps_source)
                self.assertNotIn("Remove-Item -LiteralPath $target", ps_source)
                self.assertNotIn("Move-Item -LiteralPath $staged", ps_source)
                self.assertIn("[IO.File]::Move($staged, $target, $true)", ps_source)
                self.assertIn("the existing target was not intentionally removed", ps_source)
                self.assertGreaterEqual(ps_source.count("Assert-ManagedTarget"), 3)
                self.assertLess(
                    ps_source.rindex("Assert-ManagedTarget"),
                    ps_source.index("[IO.File]::Move($staged, $target, $true)"),
                )

    def test_windows_mise_shim_match_uses_localappdata_and_ordinal_ignore_case(self) -> None:
        for tool in ("cosign", "sqlc", "terraform", "trivy", "yq"):
            source = _render(_script(tool, "ps1"), "windows", "amd64")
            with self.subTest(tool=tool):
                self.assertIn("$env:LOCALAPPDATA", source)
                self.assertIn(f"'mise\\shims\\{tool}.exe'", source)
                self.assertIn("[StringComparison]::OrdinalIgnoreCase", source)
                self.assertNotIn(".local/share/mise", source)
                self.assertNotIn("mise/installs", source)
                self.assertIn("refusing to replace foreign symlink", source)
                guards = _extract_block(source, "target-guards")
                self.assertLess(
                    guards.index("Test-KnownMiseShimLink -Item $item"),
                    guards.index("if ($item.PSIsContainer)"),
                )
                self.assertLess(
                    guards.index("if ($item.PSIsContainer)"),
                    guards.index("[IO.File]::Open"),
                )

    def test_windows_predicates_do_not_swallow_unexpected_exceptions(self) -> None:
        for tool in ("cosign", "sqlc", "terraform", "trivy", "yq"):
            source = _render(_script(tool, "ps1"), "windows", "amd64")
            with self.subTest(tool=tool):
                self.assertNotIn("catch { return $null }", source)
                self.assertIn("catch [System.IO.IOException] { return $null }", source)
                self.assertIn(
                    "catch [System.UnauthorizedAccessException] { return $null }",
                    source,
                )

    @unittest.skipUnless(BASH, "bash is required for executable header checks")
    def test_posix_header_parser_accepts_only_the_declared_cpu(self) -> None:
        cases = (
            ("linux", "amd64", _elf_header(0x3E), "amd64"),
            ("linux", "amd64", _elf_header(0xB7), "arm64"),
            ("linux", "amd64", b"broken", ""),
            ("linux", "arm64", _elf_header(0xB7), "arm64"),
            ("darwin", "arm64", _macho_header(0x0100000C), "arm64"),
            ("darwin", "arm64", _macho_header(0x01000007), "amd64"),
        )
        for tool in ("cosign", "sqlc", "terraform", "trivy", "yq"):
            for os_name, arch, payload, expected in cases:
                with self.subTest(tool=tool, os=os_name, arch=arch, expected=expected):
                    source = _render(_script(tool, "sh"), os_name, arch)
                    block = _extract_block(source, "executable-architecture")
                    with tempfile.TemporaryDirectory() as temporary:
                        path = pathlib.Path(temporary) / "candidate"
                        path.write_bytes(payload)
                        result = subprocess.run(
                            [BASH, "-c", f'{block}\nbinary_arch_of "$1"', "header-test", str(path)],
                            capture_output=True,
                            encoding="utf-8",
                            check=False,
                        )
                        self.assertEqual(result.stdout.strip(), expected)
                        self.assertEqual(result.returncode == 0, bool(expected))

    @unittest.skipUnless(PWSH, "pwsh is unavailable; PE header checks skipped")
    def test_windows_header_parser_accepts_amd64_and_arm64_only(self) -> None:
        payloads = (
            (_pe_header(0x8664), "amd64"),
            (_pe_header(0xAA64), "arm64"),
            (_pe_header(0x014C), ""),
            (b"broken", ""),
        )
        for tool in ("cosign", "sqlc", "terraform", "trivy", "yq"):
            source = _render(_script(tool, "ps1"), "windows", "amd64")
            block = _extract_block(source, "executable-architecture")
            for payload, expected in payloads:
                with self.subTest(tool=tool, expected=expected), tempfile.TemporaryDirectory() as temporary:
                    path = pathlib.Path(temporary) / "candidate.exe"
                    path.write_bytes(payload)
                    quoted = str(path).replace("'", "''")
                    command = (
                        block
                        + f"\n$result = Get-PeArchitecture -Path '{quoted}'\n"
                        + "if ($null -eq $result) { '' } else { $result }\n"
                    )
                    result = subprocess.run(
                        [PWSH, "-NoProfile", "-Command", command],
                        capture_output=True,
                        encoding="utf-8",
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), expected)

    def test_terraform_uses_embedded_key_and_isolated_gpg(self) -> None:
        sh_source = _render(_script("terraform", "sh"), "linux", "amd64")
        ps_source = _render(_script("terraform", "ps1"), "windows", "arm64")
        for source in (sh_source, ps_source):
            self.assertIn("no-auto-key-retrieve", source)
            self.assertIn("no-autostart", source)
            self.assertIn("VALIDSIG", source)
            self.assertIn(self.data["terraform"]["verification"]["publicKeyBase64"], source)
            self.assertNotIn(".well-known/pgp-key.txt", source)
        self.assertIn("Git\\usr\\bin\\gpg.exe", ps_source)
        self.assertNotIn("Get-Command gpg", ps_source)
        self.assertIn("Windows arm64 Terraform verification", ps_source)
        self.assertIn("Get-PeArchitecture -Path $gpg", ps_source)
        self.assertIn("$gpgExecutableArch", ps_source)

    def test_macos_gnupg_bootstrap_is_missing_only(self) -> None:
        rendered = _render(PACKAGE_INSTALL, "darwin", "arm64")
        start = rendered.index("if ! command -v gpg")
        end = rendered.index("fi", start)
        block = rendered[start:end]
        self.assertIn("brew install gnupg", block)


@unittest.skipIf(os.name == "nt", "POSIX behavior is not tested through Git Bash")
@unittest.skipUnless(BASH, "bash is required for POSIX behavior tests")
class PosixInstallerBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _load_data()

    def _fixture(
        self,
        root: pathlib.Path,
        tool: str,
        *,
        version: str | None = None,
        exit_code: int = 0,
        header_arch: str = "amd64",
    ) -> tuple[pathlib.Path, dict]:
        declaration = self.data[tool]
        declared = declaration["assets"]["linux-amd64"]
        selected_version = version or declaration["version"]
        payload = _archive(
            declared["archive"],
            declared["entry"],
            _binary(tool, selected_version, exit_code, header_arch),
        )
        downloads = root / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        fixture = downloads / declared["file"]
        fixture.write_bytes(payload)
        asset = dict(declared)
        asset["sha256"] = _sha256(payload)
        return fixture, {
            tool: {
                "version": declaration["version"],
                "assets": {"linux-amd64": asset},
            }
        }

    def _prepare(
        self,
        root: pathlib.Path,
        tool: str,
        fixture: pathlib.Path,
        override: dict,
        *,
        curl_fail: bool = False,
        mv_fail: bool = False,
        include_gpg: bool = True,
    ) -> tuple[pathlib.Path, pathlib.Path, dict[str, str]]:
        home = root / "home"
        bin_dir = home / ".local/bin"
        stubs = root / "stubs"
        bin_dir.mkdir(parents=True)
        stubs.mkdir(parents=True)
        _write_executable(bin_dir / "jq", _jq_stub())
        _write_executable(stubs / "curl", _curl_stub())
        _write_executable(stubs / "od", _od_stub())
        if mv_fail:
            _write_executable(stubs / "mv", "#!/bin/sh\nexit 73\n")
        if not include_gpg:
            _write_executable(stubs / "gpg", "#!/bin/sh\nexit 127\n")
        script = root / "installer.sh"
        _write_executable(
            script, _render(_script(tool, "sh"), "linux", "amd64", override)
        )
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "PATH": f"{stubs}{os.pathsep}{env['PATH']}",
                "STUB_CURL_CALLS": str(root / "curl-calls"),
                "STUB_CURL_FAIL": "1" if curl_fail else "0",
                "STUB_DOWNLOAD_DIR": str(fixture.parent),
                "PROBE_LOG": str(root / "probe-log"),
            }
        )
        return script, home, env

    def _run(
        self, script: pathlib.Path, root: pathlib.Path, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, str(script)],
            cwd=root,
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def test_fresh_install_and_no_network_fast_path(self) -> None:
        for tool in TOOLS:
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                fixture, override = self._fixture(root, tool)
                script, home, env = self._prepare(root, tool, fixture, override)
                result = self._run(script, root, env)
                target = home / ".local/bin" / tool
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(target.is_file())
                self.assertFalse(target.is_symlink())
                calls = pathlib.Path(env["STUB_CURL_CALLS"])
                self.assertTrue(calls.exists())
                calls.unlink()
                env["STUB_CURL_FAIL"] = "1"
                second = self._run(script, root, env)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertFalse(calls.exists())

    def test_failure_modes_are_nonzero_and_preserve_old_bytes(self) -> None:
        for tool in TOOLS:
            for failure in ("download", "checksum", "version", "version-exit", "publish"):
                with self.subTest(tool=tool, failure=failure), tempfile.TemporaryDirectory() as temporary:
                    root = pathlib.Path(temporary)
                    fixture, override = self._fixture(
                        root,
                        tool,
                        version="9.9.9" if failure == "version" else None,
                        exit_code=1 if failure == "version-exit" else 0,
                    )
                    if failure == "checksum":
                        override[tool]["assets"]["linux-amd64"]["sha256"] = "0" * 64
                    script, home, env = self._prepare(
                        root,
                        tool,
                        fixture,
                        override,
                        curl_fail=failure == "download",
                        mv_fail=failure == "publish",
                    )
                    target = home / ".local/bin" / tool
                    target.write_bytes(b"old bytes")
                    result = self._run(script, root, env)
                    self.assertNotEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(target.read_bytes(), b"old bytes")

    def test_wrong_or_broken_candidate_header_is_nonzero_and_preserves_old_bytes(self) -> None:
        for tool in TOOLS:
            for header_arch in ("arm64", "broken"):
                with self.subTest(tool=tool, header=header_arch), tempfile.TemporaryDirectory() as temporary:
                    root = pathlib.Path(temporary)
                    fixture, override = self._fixture(
                        root, tool, header_arch=header_arch
                    )
                    script, home, env = self._prepare(root, tool, fixture, override)
                    target = home / ".local/bin" / tool
                    target.write_bytes(b"old bytes")
                    result = self._run(script, root, env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("executable", result.stderr)
                    self.assertEqual(target.read_bytes(), b"old bytes")

    def test_wrong_cpu_local_binary_is_not_accepted_as_compliant(self) -> None:
        for tool in TOOLS:
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                fixture, override = self._fixture(root, tool)
                script, home, env = self._prepare(root, tool, fixture, override)
                target = home / ".local/bin" / tool
                _write_executable(
                    target,
                    _binary(tool, self.data[tool]["version"], header_arch="arm64"),
                )
                result = self._run(script, root, env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(pathlib.Path(env["STUB_CURL_CALLS"]).exists())
                self.assertIn(
                    "TEST_EXECUTABLE_ARCH=amd64",
                    target.read_text(encoding="utf-8"),
                )

    def test_foreign_targets_are_rejected_before_network(self) -> None:
        for tool in TOOLS:
            for kind in ("symlink", "directory"):
                with self.subTest(tool=tool, kind=kind), tempfile.TemporaryDirectory() as temporary:
                    root = pathlib.Path(temporary)
                    fixture, override = self._fixture(root, tool)
                    script, home, env = self._prepare(root, tool, fixture, override)
                    target = home / ".local/bin" / tool
                    if kind == "symlink":
                        target.symlink_to(root / "foreign")
                    else:
                        target.mkdir()
                    result = self._run(script, root, env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(pathlib.Path(env["STUB_CURL_CALLS"]).exists())

    def test_stale_mise_symlink_is_not_probed_and_is_replaced(self) -> None:
        for tool in TOOLS:
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                fixture, override = self._fixture(root, tool)
                script, home, env = self._prepare(root, tool, fixture, override)
                invoked = root / "mise-invoked"
                shim = home / ".local/share/mise/shims" / tool
                _write_executable(
                    shim,
                    "#!/bin/sh\n"
                    f"touch '{invoked}'\n"
                    + _binary(tool, self.data[tool]["version"]),
                )
                target = home / ".local/bin" / tool
                target.symlink_to(shim)
                result = self._run(script, root, env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(target.is_symlink())
                self.assertFalse(invoked.exists())

    def test_mise_symlink_to_directory_is_rejected_without_network(self) -> None:
        for tool in TOOLS:
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                fixture, override = self._fixture(root, tool)
                script, home, env = self._prepare(root, tool, fixture, override)
                shim_directory = home / ".local/share/mise/shims" / tool
                shim_directory.mkdir(parents=True)
                marker = shim_directory / "keep"
                marker.write_text("keep", encoding="utf-8")
                target = home / ".local/bin" / tool
                target.symlink_to(shim_directory)
                result = self._run(script, root, env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("resolves to a directory", result.stderr)
                self.assertFalse(pathlib.Path(env["STUB_CURL_CALLS"]).exists())
                self.assertTrue(target.is_symlink())
                self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_mise_like_but_nonexact_symlinks_are_rejected_without_network(self) -> None:
        for tool in TOOLS:
            for kind in ("installs", "other-root", "different-name", "literal-backslash"):
                with self.subTest(tool=tool, kind=kind), tempfile.TemporaryDirectory() as temporary:
                    root = pathlib.Path(temporary)
                    fixture, override = self._fixture(root, tool)
                    script, home, env = self._prepare(root, tool, fixture, override)
                    if kind == "installs":
                        referent = home / ".local/share/mise/installs" / tool / "1.0/bin" / tool
                    elif kind == "other-root":
                        referent = root / "foreign/.local/share/mise/shims" / tool
                    elif kind == "literal-backslash":
                        referent = home / ".local/share/mise\\shims" / tool
                    else:
                        referent = home / ".local/share/mise/shims" / f"{tool}-other"
                    _write_executable(referent, "#!/bin/sh\nexit 0\n")
                    target = home / ".local/bin" / tool
                    target.symlink_to(referent)
                    original = referent.read_bytes()
                    result = self._run(script, root, env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(pathlib.Path(env["STUB_CURL_CALLS"]).exists())
                    self.assertTrue(target.is_symlink())
                    self.assertEqual(referent.read_bytes(), original)

    def test_exact_dangling_mise_shim_is_replaced_without_invocation(self) -> None:
        for tool in TOOLS:
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                fixture, override = self._fixture(root, tool)
                script, home, env = self._prepare(root, tool, fixture, override)
                shim = home / ".local/share/mise/shims" / tool
                shim.parent.mkdir(parents=True)
                target = home / ".local/bin" / tool
                target.symlink_to(shim)
                self.assertFalse(shim.exists())
                result = self._run(script, root, env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(target.is_file())
                self.assertFalse(target.is_symlink())
                self.assertFalse(shim.exists())

    def test_missing_archive_entry_is_nonzero_and_preserves_old_bytes(self) -> None:
        for tool in ("sqlc", "trivy"):
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                fixture, override = self._fixture(root, tool)
                declared = self.data[tool]["assets"]["linux-amd64"]
                payload = _archive(
                    declared["archive"],
                    f"missing/{tool}",
                    _binary(tool, self.data[tool]["version"]),
                )
                fixture.write_bytes(payload)
                override[tool]["assets"]["linux-amd64"]["sha256"] = _sha256(payload)
                script, home, env = self._prepare(root, tool, fixture, override)
                target = home / ".local/bin" / tool
                target.write_bytes(b"old bytes")
                result = self._run(script, root, env)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(target.read_bytes(), b"old bytes")

    def test_trivy_probe_uses_isolated_cache_and_neutral_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            fixture, override = self._fixture(root, "trivy")
            script, _, env = self._prepare(root, "trivy", fixture, override)
            result = self._run(script, root, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = (root / "probe-log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 1)
            cwd, cache = rows[0].split("|", maxsplit=1)
            self.assertIn("/.trivy-install.", cwd)
            self.assertEqual(pathlib.Path(cache).parent, pathlib.Path(cwd))


@unittest.skipIf(os.name == "nt", "POSIX GPG behavior is tested on POSIX")
@unittest.skipUnless(BASH and GPG, "bash and gpg are required for signature tests")
class TerraformSignatureBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _load_data()
        cls.key_temp = tempfile.TemporaryDirectory()
        cls.key_home = pathlib.Path(cls.key_temp.name) / "keyring"
        cls.key_home.mkdir(mode=0o700)
        identity = "Installer Test <installer@example.invalid>"
        generate = subprocess.run(
            [
                GPG,
                "--homedir",
                str(cls.key_home),
                "--batch",
                "--passphrase",
                "",
                "--quick-generate-key",
                identity,
                "rsa2048",
                "cert",
                "0",
            ],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        if generate.returncode != 0:
            raise unittest.SkipTest(f"ephemeral GPG key generation failed: {generate.stderr}")
        listing = subprocess.run(
            [GPG, "--homedir", str(cls.key_home), "--batch", "--with-colons", "--fingerprint"],
            capture_output=True,
            encoding="utf-8",
            check=True,
        ).stdout.splitlines()
        cls.primary = next(line.split(":")[9] for line in listing if line.startswith("fpr:"))
        subprocess.run(
            [
                GPG,
                "--homedir",
                str(cls.key_home),
                "--batch",
                "--passphrase",
                "",
                "--quick-add-key",
                cls.primary,
                "rsa2048",
                "sign",
                "0",
            ],
            capture_output=True,
            encoding="utf-8",
            check=True,
        )
        listing = subprocess.run(
            [
                GPG,
                "--homedir",
                str(cls.key_home),
                "--batch",
                "--with-colons",
                "--fingerprint",
                "--fingerprint",
                cls.primary,
            ],
            capture_output=True,
            encoding="utf-8",
            check=True,
        ).stdout.splitlines()
        fingerprints = [line.split(":")[9] for line in listing if line.startswith("fpr:")]
        cls.signing = next(value for value in fingerprints if value != cls.primary)
        exported = subprocess.run(
            [GPG, "--homedir", str(cls.key_home), "--batch", "--armor", "--export", cls.primary],
            capture_output=True,
            check=True,
        ).stdout
        cls.public_key = exported

    @classmethod
    def tearDownClass(cls) -> None:
        subprocess.run(
            ["gpgconf", "--homedir", str(cls.key_home), "--kill", "all"],
            capture_output=True,
            check=False,
        )
        cls.key_temp.cleanup()

    def _sign(self, content: pathlib.Path, signature: pathlib.Path) -> None:
        subprocess.run(
            [
                GPG,
                "--homedir",
                str(self.key_home),
                "--batch",
                "--yes",
                "--passphrase",
                "",
                "--local-user",
                self.signing,
                "--detach-sign",
                "--output",
                str(signature),
                str(content),
            ],
            capture_output=True,
            check=True,
        )

    def _fixture(
        self,
        root: pathlib.Path,
        signed_hash: str | None = None,
        *,
        header_arch: str = "amd64",
    ) -> tuple[dict, pathlib.Path]:
        declaration = self.data["terraform"]
        declared = declaration["assets"]["linux-amd64"]
        downloads = root / "downloads"
        downloads.mkdir(parents=True)
        archive = downloads / declared["file"]
        archive.write_bytes(
            _archive(
                "zip",
                declared["entry"],
                _binary("terraform", declaration["version"], header_arch=header_arch),
            )
        )
        asset = dict(declared)
        asset["sha256"] = _sha256(archive.read_bytes())
        checksums = downloads / pathlib.Path(
            declaration["verification"]["checksumsUrl"]
        ).name
        checksums.write_text(
            f"{signed_hash or asset['sha256']}  {asset['file']}\n",
            encoding="utf-8",
            newline="\n",
        )
        signature = downloads / pathlib.Path(
            declaration["verification"]["signatureUrl"]
        ).name
        self._sign(checksums, signature)
        verification = dict(declaration["verification"])
        verification.update(
            {
                "checksumsSha256": _sha256(checksums.read_bytes()),
                "signatureSha256": _sha256(signature.read_bytes()),
                "publicKeySha256": _sha256(self.public_key),
                "publicKeyBase64": base64.b64encode(self.public_key).decode("ascii"),
                "primaryFingerprint": self.primary,
                "signingFingerprint": self.signing,
            }
        )
        override = {
            "terraform": {
                "version": declaration["version"],
                "assets": {"linux-amd64": asset},
                "verification": verification,
            }
        }
        return override, downloads

    def _prepare(
        self,
        root: pathlib.Path,
        override: dict,
        downloads: pathlib.Path,
        *,
        gpg_mode: str = "real",
    ) -> tuple[pathlib.Path, pathlib.Path, dict[str, str]]:
        home = root / "home"
        bin_dir = home / ".local/bin"
        stubs = root / "stubs"
        bin_dir.mkdir(parents=True)
        stubs.mkdir(parents=True)
        _write_executable(bin_dir / "jq", _jq_stub())
        _write_executable(stubs / "curl", _curl_stub())
        _write_executable(stubs / "od", _od_stub())
        if gpg_mode == "failure":
            _write_executable(stubs / "gpg", "#!/bin/sh\nexit 71\n")
        script = root / "installer.sh"
        _write_executable(
            script,
            _render(_script("terraform", "sh"), "linux", "amd64", override),
        )
        inherited = os.environ["PATH"]
        if gpg_mode == "missing":
            inherited = "/usr/bin:/bin"
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "PATH": f"{stubs}{os.pathsep}{inherited}",
                "STUB_CURL_CALLS": str(root / "curl-calls"),
                "STUB_CURL_FAIL": "0",
                "STUB_CURL_FAIL_BASENAME": "",
                "STUB_DOWNLOAD_DIR": str(downloads),
                "PROBE_LOG": str(root / "probe-log"),
            }
        )
        return script, home, env

    def _run(
        self, script: pathlib.Path, root: pathlib.Path, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, str(script)],
            cwd=root,
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def test_actual_gpg_validsig_installs_synthetic_terraform(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            override, downloads = self._fixture(root)
            script, home, env = self._prepare(root, override, downloads)
            result = self._run(script, root, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            target = home / ".local/bin/terraform"
            self.assertTrue(target.is_file())
            probe = (root / "probe-log").read_text(encoding="utf-8")
            cwd, config = probe.strip().split("|", maxsplit=1)
            self.assertIn("/.terraform-install.", cwd)
            self.assertTrue(config.endswith("/terraform.rc"))

    def test_compliant_fast_path_does_not_require_gpg_or_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            override, downloads = self._fixture(root)
            script, home, env = self._prepare(
                root, override, downloads, gpg_mode="missing"
            )
            _write_executable(
                home / ".local/bin/terraform",
                _binary("terraform", self.data["terraform"]["version"]),
            )
            env["STUB_CURL_FAIL"] = "1"
            result = self._run(script, root, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / "curl-calls").exists())

    def test_each_metadata_download_failure_is_nonzero_and_preserves_old_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            override, downloads = self._fixture(root)
            verification = override["terraform"]["verification"]
            failed_names = (
                override["terraform"]["assets"]["linux-amd64"]["file"],
                pathlib.Path(verification["checksumsUrl"]).name,
                pathlib.Path(verification["signatureUrl"]).name,
            )
            for index, failed_name in enumerate(failed_names):
                case_root = root / f"case-{index}"
                case_root.mkdir()
                case_downloads = case_root / "downloads"
                shutil.copytree(downloads, case_downloads)
                script, home, env = self._prepare(
                    case_root, override, case_downloads
                )
                target = home / ".local/bin/terraform"
                target.write_bytes(b"old bytes")
                env["STUB_CURL_FAIL_BASENAME"] = failed_name
                result = self._run(script, case_root, env)
                with self.subTest(download=failed_name):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(target.read_bytes(), b"old bytes")

    def test_tampered_key_list_and_signature_fail_and_preserve_old_bytes(self) -> None:
        for tamper in ("key", "list", "signature"):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                override, downloads = self._fixture(root)
                verification = override["terraform"]["verification"]
                if tamper == "key":
                    changed_bytes = bytearray(self.public_key)
                    changed_bytes[len(changed_bytes) // 2] ^= 1
                    changed = bytes(changed_bytes)
                    verification["publicKeyBase64"] = base64.b64encode(changed).decode("ascii")
                    verification["publicKeySha256"] = _sha256(changed)
                elif tamper == "list":
                    path = downloads / pathlib.Path(verification["checksumsUrl"]).name
                    path.write_text(path.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
                    verification["checksumsSha256"] = _sha256(path.read_bytes())
                else:
                    path = downloads / pathlib.Path(verification["signatureUrl"]).name
                    path.write_bytes(path.read_bytes()[:-1] + bytes([path.read_bytes()[-1] ^ 1]))
                    verification["signatureSha256"] = _sha256(path.read_bytes())
                script, home, env = self._prepare(root, override, downloads)
                target = home / ".local/bin/terraform"
                target.write_bytes(b"old bytes")
                result = self._run(script, root, env)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(target.read_bytes(), b"old bytes")

    def test_wrong_fingerprint_rejects_even_when_gpg_verify_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            override, downloads = self._fixture(root)
            override["terraform"]["verification"]["signingFingerprint"] = self.primary
            script, home, env = self._prepare(root, override, downloads)
            target = home / ".local/bin/terraform"
            target.write_bytes(b"old bytes")
            result = self._run(script, root, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("VALIDSIG", result.stderr)
            self.assertEqual(target.read_bytes(), b"old bytes")

    def test_missing_or_failing_gpg_is_nonzero_and_preserves_old_bytes(self) -> None:
        for mode in ("missing", "failure"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                override, downloads = self._fixture(root)
                script, home, env = self._prepare(root, override, downloads, gpg_mode=mode)
                target = home / ".local/bin/terraform"
                target.write_bytes(b"old bytes")
                result = self._run(script, root, env)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(target.read_bytes(), b"old bytes")

    def test_signed_selected_checksum_mismatch_is_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            override, downloads = self._fixture(root, signed_hash="0" * 64)
            script, home, env = self._prepare(root, override, downloads)
            target = home / ".local/bin/terraform"
            target.write_bytes(b"old bytes")
            result = self._run(script, root, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("disagrees with the declared", result.stderr)
            self.assertEqual(target.read_bytes(), b"old bytes")

    def test_archive_checksum_mismatch_is_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            override, downloads = self._fixture(root)
            asset = override["terraform"]["assets"]["linux-amd64"]
            archive = downloads / asset["file"]
            archive.write_bytes(archive.read_bytes() + b"changed")
            script, home, env = self._prepare(root, override, downloads)
            target = home / ".local/bin/terraform"
            target.write_bytes(b"old bytes")
            result = self._run(script, root, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("checksum verification failed", result.stderr)
            self.assertEqual(target.read_bytes(), b"old bytes")

    def test_wrong_or_broken_terraform_header_is_nonzero(self) -> None:
        for header_arch in ("arm64", "broken"):
            with self.subTest(header=header_arch), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                override, downloads = self._fixture(root, header_arch=header_arch)
                script, home, env = self._prepare(root, override, downloads)
                target = home / ".local/bin/terraform"
                target.write_bytes(b"old bytes")
                result = self._run(script, root, env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("executable", result.stderr)
                self.assertEqual(target.read_bytes(), b"old bytes")

    def test_missing_archive_entry_is_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            override, downloads = self._fixture(root)
            asset = override["terraform"]["assets"]["linux-amd64"]
            archive = downloads / asset["file"]
            archive.write_bytes(
                _archive(
                    "zip",
                    "missing/terraform",
                    _binary("terraform", self.data["terraform"]["version"]),
                )
            )
            asset["sha256"] = _sha256(archive.read_bytes())
            verification = override["terraform"]["verification"]
            checksums = downloads / pathlib.Path(verification["checksumsUrl"]).name
            checksums.write_text(
                f"{asset['sha256']}  {asset['file']}\n",
                encoding="utf-8",
                newline="\n",
            )
            signature = downloads / pathlib.Path(verification["signatureUrl"]).name
            self._sign(checksums, signature)
            verification["checksumsSha256"] = _sha256(checksums.read_bytes())
            verification["signatureSha256"] = _sha256(signature.read_bytes())
            script, home, env = self._prepare(root, override, downloads)
            target = home / ".local/bin/terraform"
            target.write_bytes(b"old bytes")
            result = self._run(script, root, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("failed to extract expected entry", result.stderr)
            self.assertEqual(target.read_bytes(), b"old bytes")

    def test_duplicate_selected_checksum_rows_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            override, downloads = self._fixture(root)
            verification = override["terraform"]["verification"]
            checksums = downloads / pathlib.Path(verification["checksumsUrl"]).name
            checksums.write_text(
                checksums.read_text(encoding="utf-8") * 2,
                encoding="utf-8",
                newline="\n",
            )
            signature = downloads / pathlib.Path(verification["signatureUrl"]).name
            self._sign(checksums, signature)
            verification["checksumsSha256"] = _sha256(checksums.read_bytes())
            verification["signatureSha256"] = _sha256(signature.read_bytes())
            script, home, env = self._prepare(root, override, downloads)
            target = home / ".local/bin/terraform"
            target.write_bytes(b"old bytes")
            result = self._run(script, root, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exactly one row", result.stderr)
            self.assertEqual(target.read_bytes(), b"old bytes")


@unittest.skipUnless(
    os.name == "nt" and PWSH,
    "Windows-only atomic replace tests require native PowerShell",
)
class WindowsAtomicReplaceTests(unittest.TestCase):
    def test_locked_destination_failure_preserves_old_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            target = root / "tool.exe"
            staged = root / "candidate.exe"
            target.write_bytes(b"old bytes")
            staged.write_bytes(b"new bytes")
            quoted_target = str(target).replace("'", "''")
            quoted_staged = str(staged).replace("'", "''")
            command = (
                f"$target='{quoted_target}';$staged='{quoted_staged}';"
                "$lock=[IO.File]::Open($target,[IO.FileMode]::Open,"
                "[IO.FileAccess]::Read,[IO.FileShare]::Read);"
                "try {"
                "  try {[IO.File]::Move($staged,$target,$true);exit 91}"
                "  catch [System.IO.IOException] {"
                "    if ([IO.File]::ReadAllText($target) -ne 'old bytes') {exit 92};"
                "    exit 0"
                "  }"
                "} finally {$lock.Dispose()}"
            )
            result = subprocess.run(
                [PWSH, "-NoProfile", "-Command", command],
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(target.read_bytes(), b"old bytes")

    def test_known_mise_link_skips_referent_lock_and_rejects_directory(self) -> None:
        for tool in ("cosign", "sqlc", "terraform", "trivy", "yq"):
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                local_app_data = root / "local"
                target = root / f"{tool}.exe"
                shim = local_app_data / "mise/shims" / f"{tool}.exe"
                shim.parent.mkdir(parents=True)
                shim.write_bytes(b"old bytes")
                source = _render(_script(tool, "ps1"), "windows", "amd64")
                guards = _extract_block(source, "target-guards")
                quoted_local = str(local_app_data).replace("'", "''")
                quoted_target = str(target).replace("'", "''")
                quoted_shim = str(shim).replace("'", "''")
                command = (
                    f"$env:LOCALAPPDATA='{quoted_local}';$target='{quoted_target}';"
                    f"$shim='{quoted_shim}';"
                    "try {New-Item -ItemType SymbolicLink -Path $target -Target $shim "
                    "-ErrorAction Stop|Out-Null} catch {exit 77};"
                    + guards
                    + "\n$lock=[IO.File]::Open($shim,[IO.FileMode]::Open,"
                    "[IO.FileAccess]::Read,[IO.FileShare]::None);"
                    "try {Assert-ManagedTarget;Assert-BinaryReplaceable}"
                    "finally {$lock.Dispose()};"
                    "Remove-Item -LiteralPath $target -Force;"
                    "Remove-Item -LiteralPath $shim -Force;"
                    "New-Item -ItemType Directory -Path $shim|Out-Null;"
                    "New-Item -ItemType File -Path (Join-Path $shim 'keep')|Out-Null;"
                    "try {New-Item -ItemType SymbolicLink -Path $target -Target $shim "
                    "-ErrorAction Stop|Out-Null} catch {exit 77};"
                    "try {Assert-ManagedTarget;exit 93} catch {"
                    "if(-not (Test-Path -LiteralPath (Join-Path $shim 'keep'))){exit 94};"
                    "exit 0}"
                )
                result = subprocess.run(
                    [PWSH, "-NoProfile", "-Command", command],
                    capture_output=True,
                    encoding="utf-8",
                    check=False,
                )
                if result.returncode == 77:
                    self.skipTest("Windows symbolic-link creation is not permitted")
                self.assertEqual(
                    result.returncode, 0, result.stderr + result.stdout
                )


if __name__ == "__main__":
    unittest.main()
