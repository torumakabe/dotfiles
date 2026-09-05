"""P3 workstation special installers の宣言・transaction・署名検査を検証する。"""

from __future__ import annotations

import copy
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
BASH = shutil.which("bash")
PWSH = shutil.which("pwsh")


def _load_data() -> dict:
    return tomllib.loads(DATA_PATH.read_text(encoding="utf-8"))


def _render(name: str, os_name: str, arch: str, data: dict | None = None) -> str:
    values = copy.deepcopy(data or _load_data())
    values.update(
        {
            "chezmoi": {"os": os_name, "arch": arch},
            "codespaces": False,
            "devcontainer": False,
            "isWSL": False,
            "windowsUser": "",
            "corpUser": "",
        }
    )
    result = execute_template(
        path=SOURCE_ROOT / name, data=values, source_root=SOURCE_ROOT
    )
    if result.returncode != 0:
        raise AssertionError(f"{name} failed to render: {result.stderr}")
    return result.stdout


def _write_executable(path: pathlib.Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _binary(name: str, version: str, arch: str, exit_code: int = 0) -> str:
    if name == "op":
        command = (
            '[ "$#" -eq 1 ] && [ "$1" = "--version" ] || exit 64\n'
            f"printf '%s\\n' '{version}'\n"
        )
    elif name == "cargo-make":
        command = (
            '[ "$#" -eq 2 ] && [ "$1" = "make" ] && '
            '[ "$2" = "--version" ] || exit 64\n'
            f"printf '%s\\n' 'cargo-make {version}'\n"
        )
    elif name == "makers":
        command = (
            '[ "$#" -eq 1 ] && [ "$1" = "--version" ] || exit 64\n'
            f"printf '%s\\n' 'cargo-make {version}'\n"
        )
    else:
        command = (
            '[ "$#" -eq 2 ] && [ "$1" = "version" ] && '
            '[ "$2" = "--short" ] || exit 64\n'
            f"printf '%s\\n' '{version}'\n"
        )
    return f"#!/bin/sh\n# TEST_EXECUTABLE_ARCH={arch}\n{command}exit {exit_code}\n"


def _od_stub() -> str:
    return """#!/bin/sh
file=""
for argument do file="$argument"; done
case "$(/bin/cat "$file" 2>/dev/null)" in
  *TEST_EXECUTABLE_ARCH=amd64*) printf '%s\n' '7f 45 4c 46 02 01 00 00 00 00 00 00 00 00 00 00 02 00 3e 00' ;;
  *TEST_EXECUTABLE_ARCH=arm64*) printf '%s\n' '7f 45 4c 46 02 01 00 00 00 00 00 00 00 00 00 00 02 00 b7 00' ;;
  *TEST_EXECUTABLE_ARCH=darwin-arm64*) printf '%s\n' 'cf fa ed fe 0c 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00' ;;
  *) printf '%s\n' '00 00' ;;
esac
"""


def _curl_stub() -> str:
    return """#!/bin/sh
printf 'called\n' >> "$STUB_CURL_CALLS"
output=""
url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) output="$2"; shift 2 ;;
    http*) url="$1"; shift ;;
    *) shift ;;
  esac
done
[ -n "$output" ] && [ -n "$url" ] || exit 64
cp "$STUB_DOWNLOAD_DIR/${url##*/}" "$output"
"""


def _zip(entries: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        for name, body in entries.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o755 << 16
            bundle.writestr(info, body.encode())
    return output.getvalue()


def _tar(entries: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        for name, body in entries.items():
            payload = body.encode()
            info = tarfile.TarInfo(name)
            info.mode = 0o755
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))
    return output.getvalue()


def _pe_header(machine: int) -> bytes:
    payload = bytearray(0x86)
    payload[0:2] = b"MZ"
    payload[0x3C:0x40] = (0x80).to_bytes(4, "little")
    payload[0x80:0x84] = b"PE\0\0"
    payload[0x84:0x86] = machine.to_bytes(2, "little")
    return bytes(payload)


class DeclarationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _load_data()

    def test_onepassword_pins_apt_key_policy_and_windows_signature(self) -> None:
        tool = self.data["onePassword"]
        self.assertEqual("2.39.0", tool["version"])
        self.assertEqual("/opt/homebrew", tool["homebrew"]["prefix"])
        self.assertEqual(
            "f39e7dd9dedc581ced85732832f217e0de5860a3b80279b5af4bc7c6d8157bae",
            tool["linuxApt"]["publicKeySha256"],
        )
        self.assertEqual(
            "3FEF9748469ADBE15DA7CA80AC2D62742012EA22",
            tool["linuxApt"]["primaryFingerprint"],
        )
        self.assertEqual(
            "c0c148807d8dc588750a9cc512c7243ed10a9cfd5519a5a6f0a038ad66a19c39",
            tool["linuxApt"]["policySha256"],
        )
        for platform in ("windows-amd64", "windows-arm64"):
            asset = tool["assets"][platform]
            self.assertEqual("amd64", asset["executableArch"])
            self.assertEqual(platform == "windows-arm64", asset["emulated"])
            self.assertEqual("op.exe", asset["entry"])

    def test_cargo_make_release_and_source_material_are_pinned(self) -> None:
        tool = self.data["cargoMake"]
        self.assertEqual("0.37.24", tool["version"])
        self.assertEqual("/opt/homebrew", tool["homebrew"]["prefix"])
        self.assertEqual(
            "7f304f6f709b5dbbc0efe9c84af1f42af22e0636e625c54799a60ec3d6efb64f",
            tool["source"]["sha256"],
        )
        self.assertEqual("cargo-make-0.37.24", tool["source"]["entry"])
        self.assertEqual(
            {
                "linux-amd64": "amd64",
                "windows-amd64": "amd64",
            },
            {
                platform: asset["executableArch"]
                for platform, asset in tool["assets"].items()
            },
        )
        for asset in tool["assets"].values():
            self.assertIn("secondEntry", asset)

    def test_golangci_assets_and_winget_are_native(self) -> None:
        tool = self.data["golangciLint"]
        self.assertEqual("2.13.2", tool["version"])
        self.assertEqual(
            {"darwin-arm64", "linux-amd64", "linux-arm64"},
            set(tool["assets"]),
        )
        for platform, declaration in tool["winget"]["platforms"].items():
            self.assertFalse(declaration["emulated"], platform)
            self.assertEqual(platform.removeprefix("windows-"), declaration["executableArch"])

    def test_msvc_arm64_component_and_resolver(self) -> None:
        dsc = (REPO_ROOT / "reference/windows/configuration.dsc.yaml").read_text()
        resolver = (
            SOURCE_ROOT / "run_onchange_after_20-resolve-msvc-linker.ps1.tmpl"
        ).read_text()
        self.assertIn("Microsoft.VisualStudio.Component.VC.Tools.ARM64", dsc)
        self.assertIn(r"HostARM64\ARM64\link.exe", resolver)
        self.assertIn("CARGO_TARGET_AARCH64_PC_WINDOWS_MSVC_LINKER", resolver)

    def test_apt_block_is_pinned_and_non_destructive(self) -> None:
        source = (SOURCE_ROOT / "run_once_before_10-install-packages.sh.tmpl").read_text()
        block = source.split("# >>> 1password-cli apt", 1)[1].split(
            "# <<< 1password-cli apt", 1
        )[0]
        self.assertIn("--no-options --batch --no-autostart", block)
        self.assertIn("signed-by=${system_keyring}", block)
        self.assertIn("/etc/debsig/policies/AC2D62742012EA22/1password.pol", block)
        self.assertIn("refusing to overwrite it", block)
        self.assertIn("onepassword_cli_meets_minimum", block)


@unittest.skipUnless(BASH, "bash is required")
class PosixInstallerTests(unittest.TestCase):
    def _base_environment(
        self, root: pathlib.Path
    ) -> tuple[pathlib.Path, pathlib.Path, dict[str, str]]:
        home = root / "home"
        stubs = root / "stubs"
        downloads = root / "downloads"
        home.mkdir()
        stubs.mkdir()
        downloads.mkdir()
        _write_executable(stubs / "od", _od_stub())
        calls = root / "curl-calls"
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "PATH": f"{stubs}{os.pathsep}{env['PATH']}",
                "STUB_DOWNLOAD_DIR": str(downloads),
                "STUB_CURL_CALLS": str(calls),
            }
        )
        return home, stubs, env

    def _run(self, script: str, root: pathlib.Path, env: dict[str, str]):
        script_path = root / "installer.sh"
        _write_executable(script_path, script)
        return subprocess.run(
            [BASH, str(script_path)],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_onepassword_homebrew_link_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            home, stubs, env = self._base_environment(root)
            prefix = root / "brew"
            provider = prefix / "Caskroom/1password-cli/2.39.0/op"
            _write_executable(provider, _binary("op", "2.39.0", "darwin-arm64"))
            (prefix / "bin").mkdir(parents=True)
            (prefix / "bin/op").symlink_to(provider)
            _write_executable(stubs / "brew", "#!/bin/sh\nexit 99\n")
            data = _load_data()
            data["onePassword"]["homebrew"]["prefix"] = str(prefix)
            script = _render(
                "run_after_60-install-1password-cli.sh.tmpl",
                "darwin",
                "arm64",
                data,
            )
            first = self._run(script, root, env)
            self.assertEqual(0, first.returncode, first.stderr)
            target = home / ".local/bin/op"
            self.assertTrue(target.is_symlink())
            self.assertEqual(str(provider.resolve()), os.readlink(target))
            second = self._run(script, root, env)
            self.assertEqual(0, second.returncode, second.stderr)

    def test_onepassword_rejects_foreign_and_directory_links(self) -> None:
        for directory in (False, True):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                home, stubs, env = self._base_environment(root)
                prefix = root / "brew"
                provider = prefix / "Caskroom/1password-cli/2.39.0/op"
                _write_executable(provider, _binary("op", "2.39.0", "darwin-arm64"))
                (prefix / "bin").mkdir(parents=True)
                (prefix / "bin/op").symlink_to(provider)
                _write_executable(stubs / "brew", "#!/bin/sh\nexit 99\n")
                data = _load_data()
                data["onePassword"]["homebrew"]["prefix"] = str(prefix)
                target = home / ".local/bin/op"
                target.parent.mkdir(parents=True)
                foreign = root / "foreign"
                if directory:
                    foreign.mkdir()
                    (foreign / "sentinel").write_text("keep")
                else:
                    foreign.write_text("keep")
                target.symlink_to(foreign)
                result = self._run(
                    _render(
                        "run_after_60-install-1password-cli.sh.tmpl",
                        "darwin",
                        "arm64",
                        data,
                    ),
                    root,
                    env,
                )
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(str(foreign), os.readlink(target))
                self.assertEqual("keep", (foreign / "sentinel" if directory else foreign).read_text())

    def test_cargo_make_direct_install_and_fast_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            home, stubs, env = self._base_environment(root)
            _write_executable(stubs / "curl", _curl_stub())
            entries = {
                "bundle/cargo-make": _binary("cargo-make", "0.37.24", "amd64"),
                "bundle/makers": _binary("makers", "0.37.24", "amd64"),
            }
            archive = _zip(entries)
            data = _load_data()
            asset = data["cargoMake"]["assets"]["linux-amd64"]
            asset.update(
                {
                    "file": "cargo.zip",
                    "url": "https://fixtures.invalid/cargo.zip",
                    "sha256": hashlib.sha256(archive).hexdigest(),
                    "entry": "bundle/cargo-make",
                    "secondEntry": "bundle/makers",
                }
            )
            (root / "downloads/cargo.zip").write_bytes(archive)
            script = _render(
                "run_after_62-install-cargo-make.sh.tmpl",
                "linux",
                "amd64",
                data,
            )
            first = self._run(script, root, env)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertIn("cargo-make 0.37.24", subprocess.check_output(
                [home / ".local/bin/cargo-make", "make", "--version"], text=True
            ))
            self.assertNotEqual(
                0,
                subprocess.run(
                    [home / ".local/bin/cargo-make", "--version"],
                    check=False,
                    capture_output=True,
                ).returncode,
            )
            self.assertIn(
                "cargo-make 0.37.24",
                subprocess.check_output(
                    [home / ".local/bin/makers", "--version"], text=True
                ),
            )
            self.assertNotEqual(
                0,
                subprocess.run(
                    [home / ".local/bin/makers", "make", "--version"],
                    check=False,
                    capture_output=True,
                ).returncode,
            )
            (root / "curl-calls").unlink()
            _write_executable(stubs / "curl", "#!/bin/sh\nexit 99\n")
            second = self._run(script, root, env)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertFalse((root / "curl-calls").exists())

    def test_cargo_make_homebrew_accepts_newer_package_and_links_both(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            home, stubs, env = self._base_environment(root)
            prefix = root / "brew"
            cellar = prefix / "Cellar/cargo-make/0.38.0/bin"
            stable = prefix / "opt/cargo-make"
            for name in ("cargo-make", "makers"):
                _write_executable(
                    cellar / name, _binary(name, "0.38.0", "darwin-arm64")
                )
            (prefix / "bin").mkdir(parents=True)
            (prefix / "bin/cargo-make").symlink_to(cellar / "cargo-make")
            (prefix / "bin/makers").symlink_to(cellar / "makers")
            stable.parent.mkdir(parents=True)
            stable.symlink_to(cellar.parent)
            bin_dir = home / ".local/bin"
            bin_dir.mkdir(parents=True)
            for name in ("cargo-make", "makers"):
                (bin_dir / name).symlink_to((cellar / name).resolve())
            _write_executable(stubs / "brew", "#!/bin/sh\nexit 99\n")
            data = _load_data()
            data["cargoMake"]["homebrew"]["prefix"] = str(prefix)
            result = self._run(
                _render(
                    "run_after_62-install-cargo-make.sh.tmpl",
                    "darwin",
                    "arm64",
                    data,
                ),
                root,
                env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            inodes = {}
            for name in ("cargo-make", "makers"):
                target = home / ".local/bin" / name
                self.assertTrue(target.is_symlink())
                self.assertEqual(
                    str(prefix.resolve() / "opt/cargo-make/bin" / name),
                    os.readlink(target),
                )
                inodes[name] = os.lstat(target).st_ino

            upgraded = prefix / "Cellar/cargo-make/0.39.0/bin"
            for name in ("cargo-make", "makers"):
                _write_executable(
                    upgraded / name, _binary(name, "0.39.0", "darwin-arm64")
                )
                (prefix / "bin" / name).unlink()
                (prefix / "bin" / name).symlink_to(upgraded / name)
            stable.unlink()
            stable.symlink_to(upgraded.parent)
            shutil.rmtree(cellar.parent)

            second = self._run(
                _render(
                    "run_after_62-install-cargo-make.sh.tmpl",
                    "darwin",
                    "arm64",
                    data,
                ),
                root,
                env,
            )
            self.assertEqual(0, second.returncode, second.stderr)
            for name in ("cargo-make", "makers"):
                target = home / ".local/bin" / name
                self.assertEqual(inodes[name], os.lstat(target).st_ino)
                self.assertIn(
                    "cargo-make 0.39.0",
                    subprocess.check_output(
                        [target, *(["make"] if name == "cargo-make" else []), "--version"],
                        text=True,
                    ),
                )

    def test_cargo_make_missing_second_entry_preserves_old_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            home, stubs, env = self._base_environment(root)
            _write_executable(stubs / "curl", _curl_stub())
            archive = _zip(
                {"bundle/cargo-make": _binary("cargo-make", "0.37.24", "amd64")}
            )
            data = _load_data()
            data["cargoMake"]["assets"]["linux-amd64"].update(
                {
                    "file": "cargo.zip",
                    "url": "https://fixtures.invalid/cargo.zip",
                    "sha256": hashlib.sha256(archive).hexdigest(),
                    "entry": "bundle/cargo-make",
                    "secondEntry": "bundle/makers",
                }
            )
            (root / "downloads/cargo.zip").write_bytes(archive)
            bin_dir = home / ".local/bin"
            _write_executable(bin_dir / "cargo-make", _binary("cargo-make", "old", "amd64"))
            _write_executable(bin_dir / "makers", _binary("makers", "old", "amd64"))
            before = {name: (bin_dir / name).read_bytes() for name in ("cargo-make", "makers")}
            result = self._run(
                _render(
                    "run_after_62-install-cargo-make.sh.tmpl",
                    "linux",
                    "amd64",
                    data,
                ),
                root,
                env,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(
                before,
                {name: (bin_dir / name).read_bytes() for name in ("cargo-make", "makers")},
            )

    def test_cargo_make_arm64_source_build_is_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            home, stubs, env = self._base_environment(root)
            _write_executable(stubs / "curl", _curl_stub())
            source = _tar(
                {
                    "cargo-make-0.37.24/Cargo.toml": "[package]\nname='cargo-make'\nversion='0.37.24'\n",
                    "cargo-make-0.37.24/Cargo.lock": "version = 4\n",
                }
            )
            data = _load_data()
            data["cargoMake"]["source"].update(
                {
                    "file": "cargo.crate",
                    "url": "https://fixtures.invalid/cargo.crate",
                    "sha256": hashlib.sha256(source).hexdigest(),
                }
            )
            (root / "downloads/cargo.crate").write_bytes(source)
            cargo = home / ".rustup/toolchains/test/bin/cargo"
            cargo_body = """#!/bin/sh
# TEST_EXECUTABLE_ARCH=arm64
printf '%s|%s|%s\n' "$PWD" "$CARGO_HOME" "$CARGO_TARGET_DIR" > "$BUILD_LOG"
root=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--root" ]; then root="$2"; shift 2; else shift; fi
done
mkdir -p "$root/bin"
cat >"$root/bin/cargo-make" <<'EOF'
#!/bin/sh
# TEST_EXECUTABLE_ARCH=arm64
[ "$#" -eq 2 ] && [ "$1" = "make" ] && [ "$2" = "--version" ] || exit 64
printf '%s\n' 'cargo-make 0.37.24'
EOF
cat >"$root/bin/makers" <<'EOF'
#!/bin/sh
# TEST_EXECUTABLE_ARCH=arm64
[ "$#" -eq 1 ] && [ "$1" = "--version" ] || exit 64
printf '%s\n' 'cargo-make 0.37.24'
EOF
chmod +x "$root/bin/cargo-make" "$root/bin/makers"
"""
            _write_executable(cargo, cargo_body)
            _write_executable(
                stubs / "rustup",
                f"#!/bin/sh\n[ \"$1 $2\" = 'which cargo' ] || exit 64\nprintf '%s\\n' '{cargo}'\n",
            )
            build_log = root / "build-log"
            env["BUILD_LOG"] = str(build_log)
            result = self._run(
                _render(
                    "run_after_62-install-cargo-make.sh.tmpl",
                    "linux",
                    "arm64",
                    data,
                ),
                root,
                env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            cwd, cargo_home, target = build_log.read_text().strip().split("|")
            self.assertTrue(cwd.startswith(str(home / ".local/bin")))
            self.assertTrue(cargo_home.startswith(cwd))
            self.assertTrue(target.startswith(cwd))

    def test_golangci_direct_failures_preserve_old_binary(self) -> None:
        cases = (
            ("checksum", "amd64", "2.13.2", 0, "0" * 64),
            ("architecture", "arm64", "2.13.2", 0, None),
            ("broken-header", "broken", "2.13.2", 0, None),
            ("version-exit", "amd64", "2.13.2", 9, None),
        )
        for name, arch, version, exit_code, forced_hash in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                home, stubs, env = self._base_environment(root)
                _write_executable(stubs / "curl", _curl_stub())
                body = _binary("golangci-lint", version, arch, exit_code)
                archive = _tar({"bundle/golangci-lint": body})
                data = _load_data()
                data["golangciLint"]["assets"]["linux-amd64"].update(
                    {
                        "file": "lint.tar.gz",
                        "url": "https://fixtures.invalid/lint.tar.gz",
                        "sha256": forced_hash or hashlib.sha256(archive).hexdigest(),
                        "entry": "bundle/golangci-lint",
                    }
                )
                (root / "downloads/lint.tar.gz").write_bytes(archive)
                target = home / ".local/bin/golangci-lint"
                _write_executable(target, _binary("golangci-lint", "old", "amd64"))
                before = target.read_bytes()
                result = self._run(
                    _render(
                        "run_after_66-install-golangci-lint.sh.tmpl",
                        "linux",
                        "amd64",
                        data,
                    ),
                    root,
                    env,
                )
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(before, target.read_bytes())

    def test_golangci_direct_install_and_fast_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            home, stubs, env = self._base_environment(root)
            _write_executable(stubs / "curl", _curl_stub())
            archive = _tar(
                {
                    "bundle/golangci-lint": _binary(
                        "golangci-lint", "2.13.2", "amd64"
                    )
                }
            )
            data = _load_data()
            data["golangciLint"]["assets"]["linux-amd64"].update(
                {
                    "file": "lint.tar.gz",
                    "url": "https://fixtures.invalid/lint.tar.gz",
                    "sha256": hashlib.sha256(archive).hexdigest(),
                    "entry": "bundle/golangci-lint",
                }
            )
            (root / "downloads/lint.tar.gz").write_bytes(archive)
            script = _render(
                "run_after_66-install-golangci-lint.sh.tmpl",
                "linux",
                "amd64",
                data,
            )
            first = self._run(script, root, env)
            self.assertEqual(0, first.returncode, first.stderr)
            (root / "curl-calls").unlink()
            _write_executable(stubs / "curl", "#!/bin/sh\nexit 99\n")
            second = self._run(script, root, env)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertFalse((root / "curl-calls").exists())


class WindowsContractTests(unittest.TestCase):
    def test_powershell_uses_safe_publish_and_exact_authenticode_identity(self) -> None:
        one_password = _render(
            "run_after_60-install-1password-cli.ps1.tmpl", "windows", "arm64"
        )
        cargo_make = _render(
            "run_after_62-install-cargo-make.ps1.tmpl", "windows", "arm64"
        )
        golangci = _render(
            "run_after_66-install-golangci-lint.ps1.tmpl", "windows", "arm64"
        )
        self.assertIn("Get-AuthenticodeSignature", one_password)
        self.assertIn("$signature.Status -ne", one_password)
        self.assertIn("$certificate.Subject -cne $expectedSubject", one_password)
        self.assertIn("$certificate.Issuer -cne $expectedIssuer", one_password)
        self.assertIn("EnhancedKeyUsageList", one_password)
        for script in (one_password, cargo_make, golangci):
            self.assertIn("[System.IO.File]::Move", script)
            self.assertNotIn("Move-Item -LiteralPath $staged", script)
            self.assertIn("LOCALAPPDATA", script)
        self.assertNotIn("Expand-Archive", one_password)
        self.assertNotIn("Expand-Archive", cargo_make)
        self.assertIn("expected exactly one regular", one_password)
        self.assertIn("expected exactly one regular", cargo_make)
        self.assertIn("HostARM64\\\\ARM64\\\\link", cargo_make)
        self.assertIn(
            "'CARGO_TARGET_AARCH64_PC_WINDOWS_MSVC_LINKER', 'User'",
            cargo_make,
        )
        self.assertNotIn("Launch-VsDevShell.ps1", cargo_make)
        self.assertNotIn("-HostArch", cargo_make)
        self.assertIn("ProcessArchitecture", cargo_make)
        self.assertIn("Test-PeMachine $linker 0xAA64", cargo_make)
        self.assertIn("$compiler = Join-Path $vcBin 'cl.exe'", cargo_make)
        self.assertIn("Test-PeMachine $tool 0xAA64", cargo_make)
        self.assertIn("Get-Command link.exe", cargo_make)
        self.assertIn("KitsRoot10", cargo_make)
        self.assertIn(r"bin\$version\arm64\rc.exe", cargo_make)
        self.assertIn("Test-PeMachine $resourceCompiler 0xAA64", cargo_make)
        self.assertIn("$env:INCLUDE = [string]::Join", cargo_make)
        self.assertIn("$env:LIB = [string]::Join", cargo_make)
        self.assertIn("$env:LIBPATH = $vcLib", cargo_make)
        self.assertIn("Get-Command rustup.exe", cargo_make)
        self.assertIn("'.cargo\\bin\\rustup.exe'", cargo_make)
        self.assertIn("rustup is not a native ARM64 executable", cargo_make)
        self.assertIn("$rustupFull which rustc", cargo_make)
        self.assertIn("$env:RUSTC = $rustcFull", cargo_make)
        self.assertIn("$env:CC_aarch64_pc_windows_msvc = $compiler", cargo_make)
        self.assertIn("$env:AR_aarch64_pc_windows_msvc = $librarian", cargo_make)
        self.assertIn("--target aarch64-pc-windows-msvc --locked --bins", cargo_make)
        self.assertIn("& $Path make --version", cargo_make)
        self.assertIn("& $Path --version", cargo_make)
        for variable in ("VCToolsInstallDir", "WindowsSdkDir", "INCLUDE", "LIB", "LIBPATH"):
            self.assertIn(variable, cargo_make)
        self.assertIn("Join-Path $sdkLibRoot 'ucrt\\arm64'", cargo_make)
        self.assertIn("Join-Path $sdkLibRoot 'um\\arm64'", cargo_make)
        self.assertIn("$savedEnvironment", cargo_make)
        self.assertIn("--locked --bins", cargo_make)
        self.assertIn("Microsoft\\WinGet\\Packages", golangci)
        self.assertIn("Microsoft.Winget.Source_8wekyb3d8bbwe", golangci)
        self.assertIn("$packageDirectory.Equals(", golangci)
        self.assertIn("New-Item -ItemType SymbolicLink", golangci)

    @unittest.skipUnless(PWSH, "pwsh is not available")
    def test_golangci_winget_provider_accepts_only_official_source_root(self) -> None:
        rendered = _render(
            "run_after_66-install-golangci-lint.ps1.tmpl",
            "windows",
            "amd64",
        )
        start = rendered.index("function ConvertTo-NormalizedPath")
        end = rendered.index("function Assert-TargetReplaceable", start)
        functions = rendered[start:end]
        winget_id = _load_data()["golangciLint"]["winget"]["id"]
        source_id = "Microsoft.Winget.Source_8wekyb3d8bbwe"

        for directory, expected in (
            (f"{winget_id}_{source_id}", True),
            (f"{winget_id}_Foreign.Source", False),
        ):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as temp:
                root = pathlib.Path(temp)
                packages = root / "Packages"
                links = root / "Links"
                payload = packages / directory / "golangci-lint.exe"
                payload.parent.mkdir(parents=True)
                links.mkdir()
                payload.write_bytes(b"fixture")
                alias = links / "golangci-lint.exe"
                alias.symlink_to(payload)
                quote = lambda value: str(value).replace("'", "''")
                script = f"""
$wingetLink = '{quote(alias)}'
$wingetPackages = '{quote(packages)}'
$wingetSourceIdentifier = '{source_id}'
$packageDirectoryName = '{winget_id}_{source_id}'
{functions}
try {{
    Get-WinGetBinary | Write-Output
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

    @unittest.skipUnless(PWSH, "pwsh is not available")
    def test_rendered_powershell_parses(self) -> None:
        for name in (
            "run_after_60-install-1password-cli.ps1.tmpl",
            "run_after_62-install-cargo-make.ps1.tmpl",
            "run_after_66-install-golangci-lint.ps1.tmpl",
        ):
            for arch in ("amd64", "arm64"):
                with self.subTest(name=name, arch=arch), tempfile.TemporaryDirectory() as temporary:
                    script = pathlib.Path(temporary) / "installer.ps1"
                    script.write_text(_render(name, "windows", arch), encoding="utf-8")
                    result = subprocess.run(
                        [
                            PWSH,
                            "-NoLogo",
                            "-NoProfile",
                            "-Command",
                            f"[scriptblock]::Create((Get-Content -Raw -LiteralPath '{script}')) | Out-Null",
                        ],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(0, result.returncode, result.stderr)

    @unittest.skipUnless(PWSH, "pwsh is not available")
    def test_windows_arm64_pe_machine_probe_rejects_x64_and_broken_headers(self) -> None:
        rendered = _render(
            "run_after_62-install-cargo-make.ps1.tmpl", "windows", "arm64"
        )
        function = rendered.split("function Test-PeMachine {", 1)[1].split(
            "function Test-BinaryArchitecture {", 1
        )[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            arm64 = root / "arm64.exe"
            amd64 = root / "amd64.exe"
            broken = root / "broken.exe"
            arm64.write_bytes(_pe_header(0xAA64))
            amd64.write_bytes(_pe_header(0x8664))
            broken.write_bytes(b"not-pe")
            harness = root / "probe.ps1"
            harness.write_text(
                "function Test-PeMachine {"
                + function
                + "\n"
                + f"if (-not (Test-PeMachine '{arm64}' 0xAA64)) {{ exit 10 }}\n"
                + f"if (Test-PeMachine '{amd64}' 0xAA64) {{ exit 11 }}\n"
                + f"if (Test-PeMachine '{broken}' 0xAA64) {{ exit 12 }}\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [PWSH, "-NoLogo", "-NoProfile", "-File", str(harness)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
