"""Verify the direct install paths for GitHub CLI, jq, and uv.

These three tools left mise (ADR-028 の第一弾) and are now owned by
per-tool official install paths. Every check here is static or runs a
rendered script against stubs; nothing downloads or installs anything.
"""

import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "home"
DATA_PATH = SOURCE_ROOT / ".chezmoidata.toml"
MISE_CONFIG_PATH = SOURCE_ROOT / "dot_config/mise/config.toml.tmpl"
MISE_LOCK_PATH = SOURCE_ROOT / "dot_config/mise/private_mise.lock"
HOOKS_PATH = SOURCE_ROOT / "private_dot_copilot/hooks/hooks.json"
PROFILE_PATH = SOURCE_ROOT / "dot_profile.tmpl"
USER_PATH_PS1 = SOURCE_ROOT / "run_once_after_05-setup-user-path.ps1.tmpl"
PACKAGE_INSTALL_SH = SOURCE_ROOT / "run_once_before_10-install-packages.sh.tmpl"

UV_SH = SOURCE_ROOT / "run_after_25-install-uv.sh.tmpl"
UV_PS1 = SOURCE_ROOT / "run_after_25-install-uv.ps1.tmpl"
JQ_SH = SOURCE_ROOT / "run_after_26-install-jq.sh.tmpl"
JQ_PS1 = SOURCE_ROOT / "run_after_26-install-jq.ps1.tmpl"
GH_SH = SOURCE_ROOT / "run_after_27-ensure-github-cli.sh.tmpl"
GH_PS1 = SOURCE_ROOT / "run_after_27-ensure-github-cli.ps1.tmpl"

# lockfile_platforms と同じ対象集合を "<chezmoi.os>-<chezmoi.arch>" で表す。
# darwin-amd64 は Intel Mac 用で、上流に公式 asset があるため宣言に含める。
SUPPORTED_PLATFORMS = (
    "linux-amd64",
    "linux-arm64",
    "darwin-amd64",
    "darwin-arm64",
    "windows-amd64",
    "windows-arm64",
)
# 別 CPU 向け asset への暗黙のフォールバックを禁じるため、arch ごとの識別子を固定する。
PLATFORM_ASSET_MARKERS = {
    "linux-amd64": "linux-amd64",
    "linux-arm64": "linux-arm64",
    "darwin-amd64": "macos-amd64",
    "darwin-arm64": "macos-arm64",
    "windows-amd64": "windows-amd64",
    "windows-arm64": "windows-arm64",
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

CURL_STUB = """#!/bin/sh
printf 'called\\n' >> "$STUB_CURL_CALLS"
output=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) output="$2"; shift 2 ;;
    *) shift ;;
  esac
done
if [ -z "${STUB_CURL_BODY:-}" ]; then
  exit 22
fi
cat "$STUB_CURL_BODY" > "$output"
"""


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


def _load_data() -> dict:
    return tomllib.loads(DATA_PATH.read_text(encoding="utf-8"))


def _render(
    path: pathlib.Path, os_name: str, arch: str, **context: bool | str
) -> str:
    override = {
        "chezmoi": {"os": os_name, "arch": arch},
        "codespaces": False,
        "devcontainer": False,
        "isWSL": False,
        "windowsUser": "",
        "corpUser": "",
    }
    override.update(context)
    result = subprocess.run(
        [
            "chezmoi",
            "execute-template",
            "--source",
            str(SOURCE_ROOT),
            "--override-data",
            json.dumps(override),
            "--file",
            str(path),
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise AssertionError(f"{path.name} failed to render: {result.stderr}")
    return result.stdout


def _extract_block(source: str, marker: str) -> str:
    start = source.index(f"# >>> {marker}")
    end = source.index(f"# <<< {marker}")
    return source[start:end]


def _write_executable(path: pathlib.Path, body: str) -> None:
    path.write_bytes(body.encode("utf-8"))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class DeclarationTests(unittest.TestCase):
    """home/.chezmoidata.toml は望ましい状態の宣言だけを持つ。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _load_data()

    def test_github_cli_declares_only_a_minimum_version(self) -> None:
        github_cli = self.data["githubCli"]

        self.assertEqual(set(github_cli), {"minimumVersion"})
        self.assertRegex(github_cli["minimumVersion"], r"^\d+\.\d+\.\d+$")

    def test_jq_declares_a_pinned_version_and_asset_map(self) -> None:
        jq = self.data["jq"]

        self.assertRegex(jq["version"], r"^\d+\.\d+(\.\d+)?$")
        self.assertTrue(
            jq["releaseBaseUrl"].startswith("https://github.com/jqlang/jq/releases/"),
            jq["releaseBaseUrl"],
        )
        self.assertEqual(set(jq["assets"]), set(SUPPORTED_PLATFORMS))
        for platform, asset in jq["assets"].items():
            with self.subTest(platform=platform):
                self.assertEqual(set(asset), {"file", "sha256"})
                self.assertRegex(asset["sha256"], SHA256_PATTERN)

    def test_every_jq_asset_matches_its_own_cpu(self) -> None:
        """windows-arm64 が x64 の asset へ落ちないことを含めて固定する。"""
        assets = self.data["jq"]["assets"]

        for platform, marker in PLATFORM_ASSET_MARKERS.items():
            with self.subTest(platform=platform):
                self.assertIn(marker, assets[platform]["file"])

        files = [asset["file"] for asset in assets.values()]
        self.assertEqual(len(files), len(set(files)))
        checksums = [asset["sha256"] for asset in assets.values()]
        self.assertEqual(len(checksums), len(set(checksums)))

    def test_uv_declares_a_pinned_installer(self) -> None:
        uv = self.data["uv"]

        self.assertRegex(uv["version"], r"^\d+\.\d+\.\d+$")
        self.assertTrue(
            uv["installerBaseUrl"].startswith(
                "https://github.com/astral-sh/uv/releases/"
            ),
            uv["installerBaseUrl"],
        )
        self.assertRegex(uv["shInstallerSha256"], SHA256_PATTERN)
        self.assertRegex(uv["ps1InstallerSha256"], SHA256_PATTERN)
        self.assertNotEqual(uv["shInstallerSha256"], uv["ps1InstallerSha256"])

    def test_installers_never_write_the_declaration_file(self) -> None:
        for path in (UV_SH, UV_PS1, JQ_SH, JQ_PS1, GH_SH, GH_PS1):
            with self.subTest(installer=path.name):
                self.assertNotIn(".chezmoidata", path.read_text(encoding="utf-8"))

    def test_github_cli_minimum_version_stays_aligned_with_its_consumers(self) -> None:
        """最小版は gh-stack のセットアップ要件から来ている。宣言と説明を揃える。"""
        minimum = self.data["githubCli"]["minimumVersion"]
        major_minor = ".".join(minimum.split(".")[:2])
        consumers = (
            REPO_ROOT / "home/run_after_31-install-gh-stack.sh.tmpl",
            REPO_ROOT / "home/run_after_31-install-gh-stack.ps1.tmpl",
            REPO_ROOT / "docs/operations.md",
        )
        for path in consumers:
            with self.subTest(path=path.name):
                self.assertIn(
                    f"GitHub CLI {major_minor}", path.read_text(encoding="utf-8")
                )
        self.assertIn(
            "githubCli.minimumVersion",
            (REPO_ROOT / "docs/operations.md").read_text(encoding="utf-8"),
        )


class MiseOwnershipTests(unittest.TestCase):
    """撤去した 3 つは mise の設定にも lockfile にも残らない。"""

    REMOVED_TOOLS = ("github-cli", "jq", "uv")

    def test_mise_config_no_longer_declares_the_removed_tools(self) -> None:
        config = MISE_CONFIG_PATH.read_text(encoding="utf-8")

        for tool in self.REMOVED_TOOLS:
            with self.subTest(tool=tool):
                self.assertNotRegex(config, rf"(?m)^{re.escape(tool)}\s*=")

    def test_mise_lock_no_longer_pins_the_removed_tools(self) -> None:
        lock = tomllib.loads(MISE_LOCK_PATH.read_text(encoding="utf-8"))

        for tool in self.REMOVED_TOOLS:
            with self.subTest(tool=tool):
                self.assertNotIn(tool, lock["tools"])

    def test_mise_still_owns_the_remaining_tools(self) -> None:
        lock = tomllib.loads(MISE_LOCK_PATH.read_text(encoding="utf-8"))

        for tool in ("go", "node", "kubectl", "lefthook", "bun"):
            with self.subTest(tool=tool):
                self.assertIn(tool, lock["tools"])

    def test_copilot_hooks_no_longer_force_mise_resolution(self) -> None:
        hooks = HOOKS_PATH.read_text(encoding="utf-8")

        self.assertNotIn("MISE_ENABLE_TOOLS", hooks)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class InstallerRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _load_data()

    def test_each_installer_renders_only_for_its_own_platform(self) -> None:
        cases = (
            (UV_SH, JQ_SH, GH_SH, "linux", "amd64", "windows", "amd64"),
            (UV_PS1, JQ_PS1, GH_PS1, "windows", "amd64", "linux", "amd64"),
        )
        for first, second, third, own_os, own_arch, other_os, other_arch in cases:
            for path in (first, second, third):
                with self.subTest(installer=path.name):
                    self.assertNotEqual(_render(path, own_os, own_arch).strip(), "")
                    self.assertEqual(_render(path, other_os, other_arch), "")

    def test_jq_installers_use_the_declared_asset_for_every_platform(self) -> None:
        jq = self.data["jq"]

        for platform in SUPPORTED_PLATFORMS:
            os_name, arch = platform.split("-")
            path = JQ_PS1 if os_name == "windows" else JQ_SH
            asset = jq["assets"][platform]
            expected_url = f"{jq['releaseBaseUrl']}/jq-{jq['version']}/{asset['file']}"
            with self.subTest(platform=platform):
                rendered = _render(path, os_name, arch)
                self.assertIn(asset["file"], rendered)
                self.assertIn(asset["sha256"], rendered)
                self.assertIn(expected_url, rendered)
                for other, other_asset in jq["assets"].items():
                    if other == platform:
                        continue
                    self.assertNotIn(other_asset["sha256"], rendered)

    def test_jq_installers_refuse_unsupported_platforms(self) -> None:
        jq = self.data["jq"]

        rendered = _render(JQ_SH, "linux", "riscv64")
        self.assertIn("linux-riscv64", rendered)
        self.assertIn("skipping installation", rendered)
        for asset in jq["assets"].values():
            self.assertNotIn(asset["file"], rendered)
            self.assertNotIn(asset["sha256"], rendered)

    def test_uv_installers_pin_the_official_installer(self) -> None:
        uv = self.data["uv"]
        cases = (
            (UV_SH, "linux", "amd64", "uv-installer.sh", uv["shInstallerSha256"]),
            (UV_PS1, "windows", "amd64", "uv-installer.ps1", uv["ps1InstallerSha256"]),
        )
        for path, os_name, arch, script, checksum in cases:
            with self.subTest(installer=path.name):
                rendered = _render(path, os_name, arch)
                self.assertIn(
                    f"{uv['installerBaseUrl']}/{uv['version']}/{script}", rendered
                )
                self.assertIn(checksum, rendered)
                self.assertIn(uv["version"], rendered)

    def test_uv_installers_disable_path_modification_and_stage_locally(self) -> None:
        cases = (
            (UV_SH, "linux", "amd64", "${HOME}/.local/bin", ".uv-install."),
            (UV_PS1, "windows", "amd64", ".local\\bin", ".uv-install."),
        )
        for path, os_name, arch, bin_dir, stage_prefix in cases:
            with self.subTest(installer=path.name):
                rendered = _render(path, os_name, arch)
                self.assertIn("UV_NO_MODIFY_PATH", rendered)
                self.assertIn("INSTALLER_NO_MODIFY_PATH", rendered)
                self.assertIn("UV_INSTALL_DIR", rendered)
                self.assertIn(bin_dir, rendered)
                # staging は最終パスと同じファイルシステムに置く。
                self.assertIn(stage_prefix, rendered)

    def test_windows_installers_unblock_only_after_checksum_verification(self) -> None:
        """mark-of-the-web の解除は、公式 SHA-256 との一致を確認した後だけに限る。"""
        for path, os_name, arch in ((UV_PS1, "windows", "amd64"), (JQ_PS1, "windows", "arm64")):
            with self.subTest(installer=path.name):
                rendered = _render(path, os_name, arch)
                self.assertIn("Unblock-File -LiteralPath", rendered)
                self.assertLess(
                    rendered.index("checksum verification failed"),
                    rendered.index("Unblock-File -LiteralPath"),
                )

    def test_github_cli_installers_never_download_a_binary(self) -> None:
        minimum = self.data["githubCli"]["minimumVersion"]
        cases = (
            (GH_SH, "linux", "amd64"),
            (GH_SH, "darwin", "arm64"),
            (GH_PS1, "windows", "amd64"),
        )
        for path, os_name, arch in cases:
            with self.subTest(installer=path.name, platform=f"{os_name}-{arch}"):
                rendered = _render(path, os_name, arch)
                self.assertIn(minimum, rendered)
                for forbidden in ("curl", "Invoke-WebRequest", "releases/download"):
                    self.assertNotIn(forbidden, rendered)

    def test_github_cli_installers_name_the_vendor_remediation(self) -> None:
        expected = {
            ("darwin", "arm64"): ("brew install gh", "brew upgrade gh"),
            ("linux", "amd64"): ("chezmoi apply", "apt-get install --only-upgrade gh"),
            ("windows", "amd64"): (
                "winget install --id GitHub.cli",
                "winget upgrade --id GitHub.cli",
            ),
        }
        for (os_name, arch), hints in expected.items():
            path = GH_PS1 if os_name == "windows" else GH_SH
            with self.subTest(platform=f"{os_name}-{arch}"):
                rendered = _render(path, os_name, arch)
                for hint in hints:
                    self.assertIn(hint, rendered)

    def test_windows_github_cli_uses_only_winget_locations(self) -> None:
        rendered = _render(GH_PS1, "windows", "amd64")

        self.assertIn("Join-Path $env:ProgramFiles 'GitHub CLI\\gh.exe'", rendered)
        self.assertIn(
            "Join-Path $env:LOCALAPPDATA 'Microsoft\\WinGet\\Links\\gh.exe'",
            rendered,
        )
        self.assertNotIn("Get-Command -All", rendered)
        self.assertNotIn("mise\\shims", rendered)

    def test_macos_github_cli_uses_only_the_homebrew_owned_binary(self) -> None:
        rendered = _render(GH_SH, "darwin", "arm64")

        self.assertIn("brew --prefix gh", rendered)
        self.assertIn('vendor_gh="$(resolve_homebrew_gh)"', rendered)
        self.assertNotIn(
            'vendor_gh="$(resolve_vendor_gh "${bin_dir}" "${PATH}")', rendered
        )

    def test_package_install_checks_the_vendor_owned_github_cli(self) -> None:
        source = PACKAGE_INSTALL_SH.read_text(encoding="utf-8")
        apt_block = source[source.index("vendor_gh=\"$(apt_gh_path"):source.index("{{ end -}}", source.index("vendor_gh=\"$(apt_gh_path"))]
        brew_block = source[source.index("vendor_gh=\"$(homebrew_gh_path"):source.index("{{ end -}}", source.index("vendor_gh=\"$(homebrew_gh_path"))]

        self.assertIn('gh_meets_minimum "${vendor_gh}"', apt_block)
        self.assertIn('gh_meets_minimum "${vendor_gh}"', brew_block)
        self.assertNotIn("command -v gh", apt_block)
        self.assertNotIn("command -v gh", brew_block)

    def test_codespaces_installs_github_cli_through_apt_when_needed(self) -> None:
        rendered = _render(
            PACKAGE_INSTALL_SH,
            "linux",
            "amd64",
            codespaces=True,
            devcontainer=True,
        )

        self.assertIn('vendor_gh="$(apt_gh_path || true)"', rendered)
        self.assertIn("sudo apt-get install -y -qq gh", rendered)
        self.assertNotIn("ベースイメージ側の責務", rendered)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
@unittest.skipUnless(BASH, "bash is required")
class GithubCliResolutionTests(unittest.TestCase):
    """~/.local/bin と mise shims を除いて vendor 実体を選ぶ。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.block = _extract_block(_render(GH_SH, "linux", "amd64"), "gh-resolution")

    def _run(self, snippet: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        if os.name == "nt":
            env["MSYS_NO_PATHCONV"] = "1"
        return subprocess.run(
            [BASH, "-c", f"{self.block}\n{snippet}"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_resolution_skips_local_bin_and_mise_shims(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            local_bin = root / ".local/bin"
            shims = root / ".local/share/mise/shims"
            vendor = root / "usr/bin"
            for directory in (local_bin, shims, vendor):
                directory.mkdir(parents=True)
                _write_executable(directory / "gh", "#!/bin/sh\n")

            result = self._run(
                f'resolve_vendor_gh "{_shell_path(local_bin)}" '
                f'"{":".join(_shell_path(path) for path in (local_bin, shims, vendor))}"'
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), _shell_path(vendor / "gh"))

    def test_resolution_fails_when_only_managed_directories_have_gh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            local_bin = root / ".local/bin"
            shims = root / ".local/share/mise/shims"
            for directory in (local_bin, shims):
                directory.mkdir(parents=True)
                _write_executable(directory / "gh", "#!/bin/sh\n")

            result = self._run(
                f'resolve_vendor_gh "{_shell_path(local_bin)}" '
                f'"{_shell_path(local_bin)}:{_shell_path(shims)}"'
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "")

    def test_version_comparison_handles_the_minimum_boundary(self) -> None:
        cases = (
            ("2.94.0", "2.94.0", True),
            ("2.94.1", "2.94.0", True),
            ("2.99.0", "2.94.0", True),
            ("3.0.0", "2.94.0", True),
            ("2.93.9", "2.94.0", False),
            ("2.9.0", "2.94.0", False),
            ("1.99.99", "2.94.0", False),
            ("2.94", "2.94.0", True),
            ("2.94.0-pre", "2.94.0", True),
        )
        for installed, minimum, expected in cases:
            with self.subTest(installed=installed, minimum=minimum):
                result = self._run(f'version_ge "{installed}" "{minimum}"')
                self.assertEqual(result.returncode == 0, expected, result.stderr)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
@unittest.skipUnless(BASH, "bash is required")
@unittest.skipIf(os.name == "nt", "POSIX installer behavior requires POSIX semantics")
class DirectInstallBehaviourTests(unittest.TestCase):
    """レンダリング済みスクリプトを stub 環境で実行する。通信もインストールもしない。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _load_data()

    def _environment(
        self, root: pathlib.Path, body: pathlib.Path | None
    ) -> tuple[dict[str, str], pathlib.Path]:
        stub_dir = root / "stub"
        stub_dir.mkdir()
        _write_executable(stub_dir / "curl", CURL_STUB)
        calls = root / "curl-calls.txt"

        env = dict(os.environ)
        env["HOME"] = _shell_path(root)
        if os.name == "nt":
            env["PATH"] = f"{_shell_path(stub_dir)}:/usr/bin:/bin"
        else:
            env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
        if os.name == "nt":
            env["MSYS_NO_PATHCONV"] = "1"
        env["STUB_CURL_CALLS"] = _shell_path(calls)
        if body is not None:
            env["STUB_CURL_BODY"] = _shell_path(body)
        else:
            env.pop("STUB_CURL_BODY", None)
        return env, calls

    def _run_script(
        self, source: str, root: pathlib.Path, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        script = root / "rendered-installer.sh"
        script.write_text(source, encoding="utf-8")
        return subprocess.run(
            [BASH, _shell_path(script)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_jq_makes_no_network_call_when_the_declared_version_is_present(
        self,
    ) -> None:
        version = self.data["jq"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            bin_dir.mkdir(parents=True)
            _write_executable(bin_dir / "jq", f"#!/bin/sh\necho 'jq-{version}'\n")
            env, calls = self._environment(root, None)

            result = self._run_script(_render(JQ_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(calls.exists(), "the installer contacted the network")

    def test_jq_checksum_failure_keeps_the_existing_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            bin_dir.mkdir(parents=True)
            existing = bin_dir / "jq"
            _write_executable(existing, "#!/bin/sh\necho 'jq-1.7.1'\n")
            original = existing.read_text(encoding="utf-8")
            body = root / "download.bin"
            body.write_text("not the official asset", encoding="utf-8")
            env, calls = self._environment(root, body)

            result = self._run_script(_render(JQ_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("checksum verification failed", result.stderr)
            self.assertTrue(calls.exists())
            self.assertEqual(existing.read_text(encoding="utf-8"), original)
            self.assertEqual(sorted(p.name for p in bin_dir.iterdir()), ["jq"])

    def test_jq_version_mismatch_keeps_the_existing_binary(self) -> None:
        """checksum を通った成果物でも、版が宣言と違えば置き換えない。

        ピンした SHA-256 だけを stub の実測値へ差し替え、staging から最終パスへ
        移す前の検証経路をそのまま動かす。
        """
        version = self.data["jq"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            bin_dir.mkdir(parents=True)
            existing = bin_dir / "jq"
            _write_executable(existing, "#!/bin/sh\necho 'jq-1.7.1'\n")
            original = existing.read_text(encoding="utf-8")
            body = root / "download.bin"
            body.write_text("#!/bin/sh\necho 'jq-1.6'\n", encoding="utf-8")
            env, _ = self._environment(root, body)

            source = _render(JQ_SH, "linux", "amd64").replace(
                self.data["jq"]["assets"]["linux-amd64"]["sha256"],
                _sha256(body),
            )
            result = self._run_script(source, root, env)

            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn(f"expected jq {version}", result.stderr)
            self.assertIn("1.6", result.stderr)
            self.assertEqual(existing.read_text(encoding="utf-8"), original)

    def test_jq_download_failure_warns_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            bin_dir.mkdir(parents=True)
            env, _ = self._environment(root, None)

            result = self._run_script(_render(JQ_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("failed to download", result.stderr)
            self.assertFalse((bin_dir / "jq").exists())

    def test_uv_makes_no_network_call_when_the_declared_version_is_present(
        self,
    ) -> None:
        version = self.data["uv"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            bin_dir.mkdir(parents=True)
            _write_executable(
                bin_dir / "uv", f"#!/bin/sh\necho 'uv {version} (abc 2026-01-01)'\n"
            )
            _write_executable(
                bin_dir / "uvx", f"#!/bin/sh\necho 'uvx {version} (abc 2026-01-01)'\n"
            )
            env, calls = self._environment(root, None)

            result = self._run_script(_render(UV_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(calls.exists(), "the installer contacted the network")

    def test_uv_reinstalls_when_uvx_is_missing(self) -> None:
        version = self.data["uv"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            bin_dir.mkdir(parents=True)
            _write_executable(
                bin_dir / "uv", f"#!/bin/sh\necho 'uv {version} (abc 2026-01-01)'\n"
            )
            env, calls = self._environment(root, None)

            result = self._run_script(_render(UV_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(calls.exists())

    def test_uv_reinstalls_when_uvx_has_a_different_version(self) -> None:
        version = self.data["uv"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            bin_dir.mkdir(parents=True)
            _write_executable(
                bin_dir / "uv", f"#!/bin/sh\necho 'uv {version} (abc 2026-01-01)'\n"
            )
            _write_executable(
                bin_dir / "uvx", "#!/bin/sh\necho 'uvx 0.0.1 (old)'\n"
            )
            env, calls = self._environment(root, None)

            result = self._run_script(_render(UV_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(calls.exists())

    def test_uv_checksum_failure_keeps_the_existing_binaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            bin_dir.mkdir(parents=True)
            existing = bin_dir / "uv"
            _write_executable(existing, "#!/bin/sh\necho 'uv 0.0.1 (old)'\n")
            _write_executable(bin_dir / "uvx", "#!/bin/sh\necho 'uvx 0.0.1 (old)'\n")
            original = existing.read_text(encoding="utf-8")
            body = root / "installer.txt"
            body.write_text("echo not the official installer\n", encoding="utf-8")
            env, _ = self._environment(root, body)

            result = self._run_script(_render(UV_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("checksum verification failed", result.stderr)
            self.assertEqual(existing.read_text(encoding="utf-8"), original)
            self.assertEqual(sorted(p.name for p in bin_dir.iterdir()), ["uv", "uvx"])

    def test_uv_version_mismatch_keeps_the_existing_binaries(self) -> None:
        """staging の uv が宣言と違う版なら、最終パスへ移さない。

        ピンした SHA-256 だけを stub インストーラーの実測値へ差し替え、
        UV_INSTALL_DIR への展開と版の検証をそのまま動かす。
        """
        version = self.data["uv"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            bin_dir.mkdir(parents=True)
            existing = bin_dir / "uv"
            _write_executable(existing, "#!/bin/sh\necho 'uv 0.0.1 (old)'\n")
            original = existing.read_text(encoding="utf-8")
            body = root / "installer.sh"
            body.write_text(
                "#!/bin/sh\n"
                'printf "#!/bin/sh\\necho \'uv 0.0.2 (stub)\'\\n" > "$UV_INSTALL_DIR/uv"\n'
                'printf "#!/bin/sh\\necho \'uvx 0.0.2 (stub)\'\\n" > "$UV_INSTALL_DIR/uvx"\n'
                'chmod 755 "$UV_INSTALL_DIR/uv" "$UV_INSTALL_DIR/uvx"\n',
                encoding="utf-8",
            )
            env, _ = self._environment(root, body)

            source = _render(UV_SH, "linux", "amd64").replace(
                self.data["uv"]["shInstallerSha256"], _sha256(body)
            )
            result = self._run_script(source, root, env)

            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn(f"expected uv {version}", result.stderr)
            self.assertIn("0.0.2", result.stderr)
            self.assertEqual(existing.read_text(encoding="utf-8"), original)

    def test_uv_replaces_both_binaries_after_verification(self) -> None:
        version = self.data["uv"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            bin_dir.mkdir(parents=True)
            _write_executable(bin_dir / "uv", "#!/bin/sh\necho 'uv 0.0.1 (old)'\n")
            body = root / "installer.sh"
            body.write_text(
                "#!/bin/sh\n"
                f'printf "#!/bin/sh\\necho \'uv {version} (stub)\'\\n" '
                '> "$UV_INSTALL_DIR/uv"\n'
                f'printf "#!/bin/sh\\necho \'uvx {version} (stub)\'\\n" '
                '> "$UV_INSTALL_DIR/uvx"\n'
                'chmod 755 "$UV_INSTALL_DIR/uv" "$UV_INSTALL_DIR/uvx"\n',
                encoding="utf-8",
            )
            env, _ = self._environment(root, body)

            source = _render(UV_SH, "linux", "amd64").replace(
                self.data["uv"]["shInstallerSha256"], _sha256(body)
            )
            result = self._run_script(source, root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(version, (bin_dir / "uv").read_text(encoding="utf-8"))
            self.assertTrue((bin_dir / "uvx").exists())
            # staging ディレクトリを残さない。
            self.assertEqual(
                sorted(p.name for p in bin_dir.iterdir()), ["uv", "uvx"]
            )

    def test_uv_second_move_failure_restores_both_existing_binaries(self) -> None:
        version = self.data["uv"]["version"]
        real_mv = shutil.which("mv")
        self.assertIsNotNone(real_mv)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            bin_dir.mkdir(parents=True)
            existing_uv = bin_dir / "uv"
            existing_uvx = bin_dir / "uvx"
            _write_executable(existing_uv, "#!/bin/sh\necho 'uv 0.0.1 (old)'\n")
            _write_executable(existing_uvx, "#!/bin/sh\necho 'uvx 0.0.1 (old)'\n")
            originals = (existing_uv.read_bytes(), existing_uvx.read_bytes())

            body = root / "installer.sh"
            body.write_text(
                "#!/bin/sh\n"
                f'printf "#!/bin/sh\\necho \'uv {version} (stub)\'\\n" '
                '> "$UV_INSTALL_DIR/uv"\n'
                f'printf "#!/bin/sh\\necho \'uvx {version} (stub)\'\\n" '
                '> "$UV_INSTALL_DIR/uvx"\n'
                'chmod 755 "$UV_INSTALL_DIR/uv" "$UV_INSTALL_DIR/uvx"\n',
                encoding="utf-8",
            )
            env, _ = self._environment(root, body)
            mv_stub = root / "stub/mv"
            _write_executable(
                mv_stub,
                "#!/bin/sh\n"
                'case "$1:$2" in\n'
                '  */.uv-install.*/uvx:*/.local/bin/uvx) exit 1 ;;\n'
                "esac\n"
                f'exec "{_shell_path(pathlib.Path(real_mv))}" "$@"\n',
            )

            source = _render(UV_SH, "linux", "amd64").replace(
                self.data["uv"]["shInstallerSha256"], _sha256(body)
            )
            result = self._run_script(source, root, env)

            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("restoring the previous uv installation", result.stderr)
            self.assertEqual(existing_uv.read_bytes(), originals[0])
            self.assertEqual(existing_uvx.read_bytes(), originals[1])
            self.assertEqual(sorted(p.name for p in bin_dir.iterdir()), ["uv", "uvx"])

    def test_windows_uv_pair_is_validated_and_rolled_back_together(self) -> None:
        rendered = _render(UV_PS1, "windows", "amd64")

        self.assertIn("Get-UvExecutableVersion -Path $targetUvx", rendered)
        self.assertIn("Assert-BinaryReplaceable -Path $targetUv", rendered)
        self.assertIn("Assert-BinaryReplaceable -Path $targetUvx", rendered)
        self.assertLess(
            rendered.index("Assert-BinaryReplaceable -Path $targetUvx"),
            rendered.index("Move-Item -LiteralPath $targetUv -Destination $backupUv"),
        )
        self.assertIn("previous-uv.exe", rendered)
        self.assertIn("previous-uvx.exe", rendered)
        self.assertIn("以前の実体へ戻しました", rendered)
        self.assertIn("$cleanupStageDir = $false", rendered)
        self.assertIn("復旧用ファイルは $stageDir に残しています", rendered)

    def test_posix_uv_pair_rolls_back_on_exit_and_signals(self) -> None:
        rendered = _render(UV_SH, "linux", "amd64")

        self.assertIn("trap cleanup_uv_install EXIT", rendered)
        self.assertIn("trap 'exit 130' INT", rendered)
        self.assertIn("trap 'exit 143' TERM", rendered)
        self.assertIn("transaction_started=1", rendered)
        self.assertIn("transaction_committed=1", rendered)
        self.assertIn("recovery files remain in ${stage_dir}", rendered)

    def test_github_cli_links_the_vendor_binary_over_a_stale_shim_link(self) -> None:
        minimum = self.data["githubCli"]["minimumVersion"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            shims = root / ".local/share/mise/shims"
            vendor = root / "usr/bin"
            for directory in (bin_dir, shims, vendor):
                directory.mkdir(parents=True)
            _write_executable(
                vendor / "gh", f"#!/bin/sh\necho 'gh version {minimum} (2026-01-01)'\n"
            )
            stale = bin_dir / "gh"
            stale.symlink_to(shims / "gh")

            env, _ = self._environment(root, None)
            env["PATH"] = ":".join(
                _shell_path(path) for path in (bin_dir, shims, vendor)
            ) + f":{env['PATH']}"
            result = self._run_script(_render(GH_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(os.readlink(stale), _shell_path(vendor / "gh"))
            self.assertNotIn("older than the required", result.stderr)

    def test_github_cli_below_minimum_warns_without_installing(self) -> None:
        minimum = self.data["githubCli"]["minimumVersion"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            vendor = root / "usr/bin"
            for directory in (bin_dir, vendor):
                directory.mkdir(parents=True)
            _write_executable(
                vendor / "gh", "#!/bin/sh\necho 'gh version 2.80.0 (2026-01-01)'\n"
            )

            env, calls = self._environment(root, None)
            env["PATH"] = (
                f"{_shell_path(bin_dir)}:{_shell_path(vendor)}:{env['PATH']}"
            )
            result = self._run_script(_render(GH_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("older than the required", result.stderr)
            self.assertIn(minimum, result.stderr)
            self.assertFalse(calls.exists(), "the check contacted the network")
            # 実体を複製せず、vendor 実体への symlink だけを置く。
            self.assertTrue((bin_dir / "gh").is_symlink())
            self.assertEqual(
                os.readlink(bin_dir / "gh"), _shell_path(vendor / "gh")
            )

    def test_github_cli_leaves_a_user_managed_regular_file_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            vendor = root / "usr/bin"
            for directory in (bin_dir, vendor):
                directory.mkdir(parents=True)
            _write_executable(
                vendor / "gh", "#!/bin/sh\necho 'gh version 2.99.0 (2026-01-01)'\n"
            )
            user_managed = bin_dir / "gh"
            _write_executable(user_managed, "#!/bin/sh\necho user-managed\n")
            original = user_managed.read_text(encoding="utf-8")

            env, _ = self._environment(root, None)
            env["PATH"] = (
                f"{_shell_path(bin_dir)}:{_shell_path(vendor)}:{env['PATH']}"
            )
            result = self._run_script(_render(GH_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertFalse(user_managed.is_symlink())
            self.assertEqual(user_managed.read_text(encoding="utf-8"), original)

    def test_github_cli_missing_vendor_binary_warns_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bin_dir = root / ".local/bin"
            bin_dir.mkdir(parents=True)

            env, _ = self._environment(root, None)
            env["PATH"] = _shell_path(bin_dir)
            result = self._run_script(_render(GH_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("GitHub CLI was not found", result.stderr)
            self.assertFalse((bin_dir / "gh").exists())


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
@unittest.skipUnless(shutil.which("sh"), "sh is required")
class PosixPathOrderTests(unittest.TestCase):
    """~/.local/bin は mise shims より前に来る。"""

    def _resolved_path(self, os_name: str, initial: str, home: pathlib.Path) -> list[str]:
        profile = home / ".profile"
        profile.write_text(_render(PROFILE_PATH, os_name, "arm64"), encoding="utf-8")
        result = subprocess.run(
            ["sh", "-c", f'. "{profile}"; printf "%s" "$PATH"'],
            check=False,
            capture_output=True,
            text=True,
            env={"HOME": str(home), "PATH": initial},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.split(":")

    def test_local_bin_precedes_mise_shims(self) -> None:
        for os_name in ("linux", "darwin"):
            with self.subTest(os=os_name), tempfile.TemporaryDirectory() as temp_dir:
                home = pathlib.Path(temp_dir)
                local_bin = home / ".local/bin"
                shims = home / ".local/share/mise/shims"
                for directory in (local_bin, shims):
                    directory.mkdir(parents=True)

                entries = self._resolved_path(os_name, "/usr/bin:/bin", home)

                self.assertLess(
                    entries.index(str(local_bin)), entries.index(str(shims))
                )

    def test_an_existing_entry_is_moved_to_the_front(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            local_bin = home / ".local/bin"
            shims = home / ".local/share/mise/shims"
            for directory in (local_bin, shims):
                directory.mkdir(parents=True)

            entries = self._resolved_path(
                "linux", f"/usr/bin:{local_bin}:/bin", home
            )

            self.assertEqual(entries[0], str(local_bin))
            self.assertEqual(entries.count(str(local_bin)), 1)
            self.assertLess(entries.index(str(local_bin)), entries.index(str(shims)))


class WindowsPathOrderTests(unittest.TestCase):
    def test_user_path_script_puts_local_bin_before_mise_shims(self) -> None:
        source = USER_PATH_PS1.read_text(encoding="utf-8")

        self.assertIn("-Leading @($localBinDir, $shimsDir)", source)
        self.assertLess(
            source.index("$localBinDir = Join-Path $HOME '.local\\bin'"),
            source.index("$shimsDir = Join-Path $env:LOCALAPPDATA 'mise\\shims'"),
        )

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
    def test_path_normalization_dedupes_case_and_separator_variants(self) -> None:
        block = _extract_block(
            _render(USER_PATH_PS1, "windows", "amd64"), "user-path-normalization"
        )
        script = (
            f"{block}\n"
            "$leading = @('C:\\Users\\x\\.local\\bin', 'C:\\Users\\x\\AppData\\mise\\shims')\n"
            "$existing = @("
            "'C:/Users/x/AppData/mise/shims/', "
            "'C:\\Windows\\System32', "
            "'c:\\users\\x\\.local\\bin', "
            "'C:\\Windows\\System32\\', "
            "'C:\\Tools')\n"
            "(Get-OrderedPathEntries -Leading $leading -Existing $existing) -join ';'\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = pathlib.Path(temp_dir) / "path.ps1"
            script_path.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "C:\\Users\\x\\.local\\bin;C:\\Users\\x\\AppData\\mise\\shims;"
            "C:\\Windows\\System32;C:\\Tools",
        )


def _sha256(path: pathlib.Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
