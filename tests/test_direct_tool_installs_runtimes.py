"""Verify the direct install paths for the P1 runtimes.

Go / Node.js / .NET SDK / Bun / pnpm / TypeScript グローバル CLI /
typescript-language-server は ADR-028 第二弾で mise から離れ、それぞれの
公式ソースから直接導入するようになった (typescript-lsp 専用の TypeScript
6.0.3 は tsserver.js 提供専用の既存依存で、ここでは import 元の TypeScript
CLI と別に検証する)。すべてのチェックは静的解析か、レンダリングした
スクリプトを合成した fixture / stub に対して実行するだけで、実際のダウン
ロードやインストールは一切行わない。
"""

import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import tomllib
import unittest
import zipfile


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "home"
DATA_PATH = SOURCE_ROOT / ".chezmoidata.toml"

GO_SH = SOURCE_ROOT / "run_after_15-install-go.sh.tmpl"
GO_PS1 = SOURCE_ROOT / "run_after_15-install-go.ps1.tmpl"
NODE_SH = SOURCE_ROOT / "run_after_16-install-node.sh.tmpl"
NODE_PS1 = SOURCE_ROOT / "run_after_16-install-node.ps1.tmpl"
DOTNET_SH = SOURCE_ROOT / "run_after_17-install-dotnet.sh.tmpl"
DOTNET_PS1 = SOURCE_ROOT / "run_after_17-install-dotnet.ps1.tmpl"
BUN_SH = SOURCE_ROOT / "run_after_18-install-bun.sh.tmpl"
BUN_PS1 = SOURCE_ROOT / "run_after_18-install-bun.ps1.tmpl"
PNPM_SH = SOURCE_ROOT / "run_after_19-install-pnpm.sh.tmpl"
PNPM_PS1 = SOURCE_ROOT / "run_after_19-install-pnpm.ps1.tmpl"
TS_CLI_SH = SOURCE_ROOT / "run_after_21-install-typescript-cli.sh.tmpl"
TS_CLI_PS1 = SOURCE_ROOT / "run_after_21-install-typescript-cli.ps1.tmpl"
TS_LSP_SH = SOURCE_ROOT / "run_after_22-install-typescript-lsp.sh.tmpl"
TS_LSP_PS1 = SOURCE_ROOT / "run_after_22-install-typescript-lsp.ps1.tmpl"
TSLS_SH = SOURCE_ROOT / "run_after_23-install-typescript-language-server.sh.tmpl"
TSLS_PS1 = SOURCE_ROOT / "run_after_23-install-typescript-language-server.ps1.tmpl"

ALL_RUNTIME_SCRIPTS = (
    GO_SH, GO_PS1, NODE_SH, NODE_PS1, DOTNET_SH, DOTNET_PS1,
    BUN_SH, BUN_PS1, PNPM_SH, PNPM_PS1,
    TS_CLI_SH, TS_CLI_PS1, TS_LSP_SH, TS_LSP_PS1, TSLS_SH, TSLS_PS1,
)
POSIX_RUNTIME_SCRIPTS = (
    GO_SH, NODE_SH, DOTNET_SH, BUN_SH, PNPM_SH,
    TS_CLI_SH, TS_LSP_SH, TSLS_SH,
)

# P1 の 5 ツール (go/node/dotnet/bun/pnpm) は darwin-amd64 (Intel Mac) を
# 対象にしない。uv/jq/github-cli の 6 プラットフォーム集合とは異なる。
RUNTIME_PLATFORMS = (
    "linux-amd64",
    "linux-arm64",
    "darwin-arm64",
    "windows-amd64",
    "windows-arm64",
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SHA512_PATTERN = re.compile(r"^[0-9a-f]{128}$")


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


def _write_executable(path: pathlib.Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("utf-8"))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha512_bytes(data: bytes) -> str:
    return hashlib.sha512(data).hexdigest()


def _make_tar_gz(
    files: dict[str, str], executables: set[str], root_dir: str | None
) -> bytes:
    """files/executables のキーは root_dir を含まない相対パス。

    root_dir を指定すると単一の頂点ディレクトリでラップする (go/node が
    --strip-components=1 で剥がす対象)。None ならフラット (dotnet/pnpm)。
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for relpath, content in files.items():
            data = content.encode("utf-8")
            arcname = f"{root_dir}/{relpath}" if root_dir else relpath
            info = tarfile.TarInfo(name=arcname)
            info.size = len(data)
            info.mode = 0o755 if relpath in executables else 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _make_zip(files: dict[str, str], executables: set[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for relpath, content in files.items():
            data = content.encode("utf-8")
            zi = zipfile.ZipInfo(relpath)
            mode = 0o755 if relpath in executables else 0o644
            zi.external_attr = (mode & 0xFFFF) << 16
            zf.writestr(zi, data)
    return buf.getvalue()


class DeclarationTests(unittest.TestCase):
    """home/.chezmoidata.toml は望ましい状態の宣言だけを持つ。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _load_data()

    def test_go_declares_pinned_version_and_asset_map(self) -> None:
        go = self.data["go"]

        self.assertRegex(go["version"], r"^\d+\.\d+\.\d+$")
        self.assertTrue(
            go["downloadBaseUrl"].startswith("https://dl.google.com/go"),
            go["downloadBaseUrl"],
        )
        self.assertEqual(set(go["assets"]), set(RUNTIME_PLATFORMS))
        for platform, asset in go["assets"].items():
            with self.subTest(platform=platform):
                self.assertEqual(set(asset), {"file", "sha256"})
                self.assertRegex(asset["sha256"], SHA256_PATTERN)

    def test_node_declares_pinned_version_and_asset_map(self) -> None:
        node = self.data["node"]

        self.assertRegex(node["version"], r"^\d+\.\d+\.\d+$")
        self.assertTrue(
            node["downloadBaseUrl"].startswith("https://nodejs.org/dist"),
            node["downloadBaseUrl"],
        )
        self.assertEqual(set(node["assets"]), set(RUNTIME_PLATFORMS))
        for platform, asset in node["assets"].items():
            with self.subTest(platform=platform):
                self.assertRegex(asset["sha256"], SHA256_PATTERN)
                if platform.startswith("windows-"):
                    self.assertIn("innerDir", asset)

    def test_dotnet_declares_pinned_version_and_sha512_asset_map(self) -> None:
        dotnet = self.data["dotnet"]

        self.assertRegex(dotnet["version"], r"^\d+\.\d+\.\d+$")
        self.assertTrue(
            dotnet["downloadBaseUrl"].startswith(
                "https://builds.dotnet.microsoft.com/dotnet/Sdk"
            ),
            dotnet["downloadBaseUrl"],
        )
        self.assertEqual(set(dotnet["assets"]), set(RUNTIME_PLATFORMS))
        for platform, asset in dotnet["assets"].items():
            with self.subTest(platform=platform):
                self.assertEqual(set(asset), {"file", "sha512"})
                self.assertRegex(asset["sha512"], SHA512_PATTERN)

    def test_bun_declares_pinned_version_and_asset_map(self) -> None:
        bun = self.data["bun"]

        self.assertRegex(bun["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(bun["releaseTag"], f"bun-v{bun['version']}")
        self.assertTrue(
            bun["releaseBaseUrl"].startswith(
                "https://github.com/oven-sh/bun/releases/download"
            ),
            bun["releaseBaseUrl"],
        )
        self.assertEqual(set(bun["assets"]), set(RUNTIME_PLATFORMS))
        for platform, asset in bun["assets"].items():
            with self.subTest(platform=platform):
                self.assertEqual(set(asset), {"file", "innerFile", "sha256"})
                self.assertRegex(asset["sha256"], SHA256_PATTERN)
                self.assertTrue(asset["file"].endswith(".zip"), asset["file"])

    def test_pnpm_declares_pinned_version_and_asset_map(self) -> None:
        pnpm = self.data["pnpm"]

        self.assertRegex(pnpm["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(pnpm["releaseTag"], f"v{pnpm['version']}")
        self.assertTrue(
            pnpm["releaseBaseUrl"].startswith(
                "https://github.com/pnpm/pnpm/releases/download"
            ),
            pnpm["releaseBaseUrl"],
        )
        self.assertEqual(set(pnpm["assets"]), set(RUNTIME_PLATFORMS))
        for platform, asset in pnpm["assets"].items():
            with self.subTest(platform=platform):
                self.assertEqual(set(asset), {"file", "entrypoint", "sha256"})
                self.assertRegex(asset["sha256"], SHA256_PATTERN)

    def test_typescript_cli_and_language_server_declare_versions_only(self) -> None:
        """npm ミラーは dist.integrity を欠くため、存在しない検証を宣言しない。"""
        for key, expected_prefix in (
            ("typescriptCli", "7."),
            ("typescriptLanguageServer", "6."),
        ):
            with self.subTest(tool=key):
                spec = self.data[key]
                self.assertEqual(set(spec), {"version"})
                self.assertRegex(spec["version"], r"^\d+\.\d+\.\d+$")
                self.assertTrue(spec["version"].startswith(expected_prefix))

    def test_typescript_lsp_stays_on_the_stable_dedicated_version(self) -> None:
        """TS7 系は tsserver を同梱しないため、専用 LSP 依存は 6.0.3 に固定。"""
        lsp = self.data["typescriptLsp"]

        self.assertEqual(set(lsp), {"version"})
        self.assertEqual(lsp["version"], "6.0.3")
        self.assertNotEqual(lsp["version"], self.data["typescriptCli"]["version"])

    def test_every_runtime_asset_matches_its_own_cpu(self) -> None:
        """windows-arm64 が x64 の asset へ暗黙に落ちないことを含めて固定する。

        ベンダーごとにファイル名の CPU 表記 (arm64/aarch64, amd64/x64) が
        異なるため、共通の marker 文字列ではなく arch カテゴリ単位で判定する。
        """
        arm_markers = ("arm64", "aarch64")
        amd_markers = ("amd64", "x64")
        for tool in ("go", "node", "dotnet", "bun"):
            with self.subTest(tool=tool):
                assets = self.data[tool]["assets"]
                for platform in RUNTIME_PLATFORMS:
                    asset_file = assets[platform]["file"].lower()
                    is_arm = platform.endswith("arm64")
                    with self.subTest(platform=platform):
                        if is_arm:
                            self.assertTrue(
                                any(marker in asset_file for marker in arm_markers),
                                asset_file,
                            )
                        else:
                            self.assertTrue(
                                any(marker in asset_file for marker in amd_markers),
                                asset_file,
                            )
                            self.assertFalse(
                                any(marker in asset_file for marker in arm_markers),
                                asset_file,
                            )
                files = [asset["file"] for asset in assets.values()]
                self.assertEqual(len(files), len(set(files)))

    def test_runtime_installers_never_write_the_declaration_file(self) -> None:
        for path in ALL_RUNTIME_SCRIPTS:
            with self.subTest(installer=path.name):
                self.assertNotIn(".chezmoidata", path.read_text(encoding="utf-8"))

    def test_posix_entrypoints_use_private_unique_staging_and_exact_mise_names(
        self,
    ) -> None:
        for path in POSIX_RUNTIME_SCRIPTS:
            with self.subTest(installer=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn('"${link}.tmp"', source)
                self.assertNotIn('"${mise_shims_dir}"/*', source)
                self.assertIn('mktemp -d "${bin_dir}/.', source)
                self.assertIn("refusing to replace it", source)

    def test_typescript_lsp_and_language_server_have_no_cross_dependency(self) -> None:
        """typescript-language-server は typescript を自身の依存に持たない。"""
        tsls_source = TSLS_SH.read_text(encoding="utf-8")

        self.assertNotIn('"typescript@', tsls_source)
        self.assertIn('"typescript-language-server@${tsls_version}"', tsls_source)

    def test_mise_shim_link_script_excludes_migrated_p1_binary_names(self) -> None:
        """P1 移行後に mise shims ディレクトリへ残り得る古い shim を

        誤って ~/.local/bin へ symlink しないよう、移行済みツールが公開して
        いたバイナリ名を EXCLUDE_EXACT へ列挙しておく必要がある。列挙漏れが
        あると、GUI 起動プロセス (~/.local/bin のみを PATH に含む) から古い
        mise 管理版が復活して見える。
        """
        link_script = SOURCE_ROOT / "run_onchange_after_21-link-mise-shims.sh.tmpl"
        source = link_script.read_text(encoding="utf-8")
        match = re.search(r"EXCLUDE_EXACT=\((.*?)\)", source, re.DOTALL)
        self.assertIsNotNone(match, "EXCLUDE_EXACT array not found")
        excluded = set(match.group(1).split())

        expected_p1_binary_names = {
            "go", "gofmt",
            "node", "npm", "npx",
            "dotnet", "dnx",
            "pnpm",
            "bun", "bunx",
            "tsc", "tsserver", "typescript-language-server",
        }
        missing = expected_p1_binary_names - excluded
        self.assertEqual(set(), missing)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class InstallerRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _load_data()

    def test_archive_installers_refuse_unsupported_platforms(self) -> None:
        """darwin-amd64 (Intel Mac) は宣言に無いため、別 CPU へ落とさず警告して終わる。"""
        for sh_path, tool_label in (
            (GO_SH, "Go"),
            (NODE_SH, "Node.js"),
            (DOTNET_SH, ".NET SDK"),
            (BUN_SH, "Bun"),
            (PNPM_SH, "pnpm"),
        ):
            with self.subTest(tool=tool_label):
                rendered = _render(sh_path, "darwin", "amd64")
                self.assertIn(
                    f"Warning: {tool_label}", rendered
                )
                self.assertIn("has no official asset for darwin-amd64", rendered)
                self.assertIn("exit 0", rendered)

    def test_archive_installers_use_the_declared_asset_for_every_platform(
        self,
    ) -> None:
        cases = (
            (GO_SH, "go", "downloadBaseUrl"),
            (NODE_SH, "node", "downloadBaseUrl"),
            (DOTNET_SH, "dotnet", "downloadBaseUrl"),
        )
        for sh_path, key, _ in cases:
            for platform in RUNTIME_PLATFORMS:
                if platform.startswith("windows-"):
                    continue
                os_name, arch = platform.split("-", 1)
                with self.subTest(tool=key, platform=platform):
                    rendered = _render(sh_path, os_name, arch)
                    asset = self.data[key]["assets"][platform]
                    self.assertIn(asset["file"], rendered)

    def test_typescript_cli_and_tsls_use_prefix_install_not_global(self) -> None:
        for path in (TS_CLI_SH, TS_LSP_SH, TSLS_SH):
            with self.subTest(installer=path.name):
                rendered = _render(path, "linux", "amd64")
                self.assertIn("--prefix", rendered)
                self.assertIn("--no-save", rendered)
                self.assertIn("--package-lock=false", rendered)
                self.assertNotIn("install --global", rendered)
                self.assertNotIn(" -g ", rendered)


class ArchiveInstallBehaviourTests(unittest.TestCase):
    """staging → checksum・版検証 → atomic swap を、合成 fixture で確認する。"""

    @classmethod
    def setUpClass(cls) -> None:
        if BASH is None:
            raise unittest.SkipTest("bash is required for direct-install tests")
        cls.data = _load_data()

    def _run_script(
        self, source: str, root: pathlib.Path, extra_env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        script = root / "rendered-installer.sh"
        script.write_text(source, encoding="utf-8")
        env = dict(os.environ)
        env["HOME"] = _shell_path(root)
        env.update(extra_env)
        return subprocess.run(
            [BASH, _shell_path(script)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def _stub_curl(self, root: pathlib.Path, body: pathlib.Path | None) -> dict[str, str]:
        stub_dir = root / "stub-bin"
        stub_dir.mkdir(parents=True, exist_ok=True)
        _write_executable(
            stub_dir / "curl",
            "#!/bin/sh\n"
            "output=\"\"\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "  case \"$1\" in\n"
            "    -o) output=\"$2\"; shift 2 ;;\n"
            "    *) shift ;;\n"
            "  esac\n"
            "done\n"
            + (
                "cat \"$STUB_CURL_BODY\" > \"$output\"\n"
                if body is not None
                else "exit 22\n"
            ),
        )
        env = {"PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}"}
        if body is not None:
            env["STUB_CURL_BODY"] = _shell_path(body)
        return env

    def _go_binary(self, version: str, require_local_probe: bool = False) -> str:
        guard = ""
        if require_local_probe:
            guard = (
                'if [ "${GOTOOLCHAIN:-}" != local ] '
                '|| [ "${GOWORK:-}" != off ] || [ "$PWD" != / ]; then\n'
                "  echo 'go version probe environment rejected' >&2\n"
                "  exit 86\n"
                "fi\n"
            )
        return (
            "#!/bin/sh\n"
            f"{guard}"
            f'echo "go version go{version} linux/amd64"\n'
        )

    def _go_archive(
        self, version: str, require_local_probe: bool = False
    ) -> bytes:
        return _make_tar_gz(
            {
                "bin/go": self._go_binary(version, require_local_probe),
                "bin/gofmt": "#!/bin/sh\necho gofmt-stub\n",
                "pkg/tool/linux_amd64/compile": "stub compiler\n",
            },
            {"bin/go", "bin/gofmt"},
            root_dir="go",
        )

    def _write_go_fixture(
        self,
        final_root: pathlib.Path,
        version: str,
        require_local_probe: bool = False,
    ) -> None:
        _write_executable(
            final_root / "bin/go",
            self._go_binary(version, require_local_probe),
        )
        _write_executable(final_root / "bin/gofmt", "#!/bin/sh\necho gofmt-stub\n")
        (final_root / "pkg/tool/linux_amd64").mkdir(parents=True)
        (final_root / "pkg/tool/linux_amd64/compile").write_text("stub compiler\n")

    def _stub_go_second_entrypoint_publish_failure(
        self, root: pathlib.Path, env: dict[str, str]
    ) -> pathlib.Path:
        real_mv = shutil.which("mv")
        if real_mv is None:
            self.skipTest("mv is required for entrypoint transaction tests")
        stub_dir = root / "stub-bin"
        marker = root / "go-second-publish-failed"
        _write_executable(
            stub_dir / "mv",
            "#!/bin/sh\n"
            'case "${1:-}|${2:-}" in\n'
            '  */.go-entrypoints.*/gofmt\\|*/.local/bin/gofmt)\n'
            '    if [ ! -e "$STUB_MV_FAILURE_USED" ]; then\n'
            '      : > "$STUB_MV_FAILURE_USED"\n'
            "      exit 73\n"
            "    fi\n"
            "    ;;\n"
            "esac\n"
            'exec "$REAL_MV" "$@"\n',
        )
        env["REAL_MV"] = real_mv
        env["STUB_MV_FAILURE_USED"] = _shell_path(marker)
        return marker

    def _node_archive(self, version: str) -> bytes:
        return _make_tar_gz(
            {
                "bin/node": f"#!/bin/sh\necho \"v{version}\"\n",
                "bin/npm": "#!/bin/sh\necho npm-stub\n",
                "bin/npx": "#!/bin/sh\necho npx-stub\n",
                "lib/node_modules/npm/bin/npm-cli.js": "// npm-cli stub\n",
                "lib/node_modules/npm/bin/npx-cli.js": "// npx-cli stub\n",
                "lib/node_modules/npm/package.json": '{"name": "npm"}\n',
            },
            {"bin/node", "bin/npm", "bin/npx"},
            root_dir=f"node-v{version}-linux-x64",
        )

    def _dotnet_archive(self, version: str, include_dnx: bool = True) -> bytes:
        files = {
            "dotnet": f"#!/bin/sh\necho {version}\n",
            f"sdk/{version}/dotnet.dll": "stub dll\n",
            f"sdk/{version}/Sdks/Microsoft.NET.Sdk/Sdk/Sdk.props": "<Project />\n",
        }
        executables = {"dotnet"}
        if include_dnx:
            files["dnx"] = "#!/bin/sh\necho REAL-DNX\n"
            executables.add("dnx")
        return _make_tar_gz(
            files,
            executables,
            root_dir=None,
        )

    def _write_dotnet_fixture(self, final_root: pathlib.Path, version: str) -> None:
        _write_executable(final_root / "dotnet", f"#!/bin/sh\necho {version}\n")
        _write_executable(final_root / "dnx", "#!/bin/sh\necho REAL-DNX\n")
        sdk_dir = final_root / "sdk" / version
        (sdk_dir / "Sdks/Microsoft.NET.Sdk/Sdk").mkdir(parents=True)
        (sdk_dir / "dotnet.dll").write_text("stub dll\n")
        (sdk_dir / "Sdks/Microsoft.NET.Sdk/Sdk/Sdk.props").write_text("<Project />\n")

    def _stub_dotnet_second_entrypoint_publish_failure(
        self, root: pathlib.Path, env: dict[str, str]
    ) -> None:
        real_mv = shutil.which("mv")
        if real_mv is None:
            self.skipTest("mv is required for entrypoint transaction tests")
        stub_dir = root / "stub-bin"
        marker = root / "dotnet-second-publish-failed"
        _write_executable(
            stub_dir / "mv",
            "#!/bin/sh\n"
            'case "${1:-}|${2:-}" in\n'
            '  */.dotnet-entrypoints.*/dnx\\|*/.local/bin/dnx)\n'
            '    if [ ! -e "$STUB_MV_FAILURE_USED" ]; then\n'
            '      : > "$STUB_MV_FAILURE_USED"\n'
            "      exit 73\n"
            "    fi\n"
            "    ;;\n"
            "esac\n"
            'exec "$REAL_MV" "$@"\n',
        )
        env["REAL_MV"] = real_mv
        env["STUB_MV_FAILURE_USED"] = _shell_path(marker)

    def _pnpm_binary(
        self, version: str, require_offline_probe: bool = False
    ) -> str:
        guard = ""
        if require_offline_probe:
            guard = (
                'if [ "${PNPM_CONFIG_PM_ON_FAIL:-}" != ignore ] '
                '|| [ "$PWD" != / ]; then\n'
                "  echo 'pnpm version probe environment rejected' >&2\n"
                "  exit 86\n"
                "fi\n"
            )
        return f"#!/bin/sh\n{guard}echo '{version}'\n"

    def _pnpm_archive(
        self, version: str, require_offline_probe: bool = False
    ) -> bytes:
        return _make_tar_gz(
            {
                "pnpm": self._pnpm_binary(version, require_offline_probe),
                "dist/pnpm.mjs": "// pnpm bundle stub\n",
                "dist/worker.js": "// worker stub\n",
            },
            {"pnpm"},
            root_dir=None,
        )

    def _write_pnpm_fixture(
        self,
        final_root: pathlib.Path,
        version: str,
        require_offline_probe: bool = False,
    ) -> None:
        _write_executable(
            final_root / "pnpm",
            self._pnpm_binary(version, require_offline_probe),
        )
        (final_root / "dist").mkdir(parents=True)
        (final_root / "dist/pnpm.mjs").write_text("// pnpm bundle stub\n")
        (final_root / "dist/worker.js").write_text("// worker stub\n")

    def test_go_fresh_install_extracts_and_verifies_the_entrypoint(self) -> None:
        version = self.data["go"]["version"]
        archive = self._go_archive(version)
        asset_sha256 = _sha256_bytes(archive)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            body = root / "download.bin"
            body.write_bytes(archive)
            source = _render(GO_SH, "linux", "amd64").replace(
                self.data["go"]["assets"]["linux-amd64"]["sha256"], asset_sha256
            )
            env = self._stub_curl(root, body)

            result = self._run_script(source, root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            entrypoint = (
                root / ".local/share/chezmoi-dotfiles/go/bin/go"
            )
            self.assertTrue(entrypoint.is_file())
            check = subprocess.run(
                [str(entrypoint), "version"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn(version, check.stdout)
            # ~/.local/bin へ go/gofmt の native symlink も同時に発行される。
            local_bin_go = root / ".local/bin/go"
            local_bin_gofmt = root / ".local/bin/gofmt"
            self.assertTrue(local_bin_go.is_symlink())
            self.assertEqual(
                local_bin_go.resolve(), (root / ".local/share/chezmoi-dotfiles/go/bin/go").resolve()
            )
            self.assertTrue(local_bin_gofmt.is_symlink())

    def test_go_makes_no_network_call_when_the_declared_version_is_present(
        self,
    ) -> None:
        version = self.data["go"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = root / ".local/share/chezmoi-dotfiles/go"
            entrypoint = final_root / "bin/go"
            self._write_go_fixture(final_root, version)
            env = self._stub_curl(root, None)
            env["STUB_CURL_MUST_NOT_RUN"] = "1"

            result = self._run_script(_render(GO_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            # entrypoint はそのまま (再インストールされていない)。
            self.assertIn(version, entrypoint.read_text(encoding="utf-8"))
            # 版が一致していても ~/.local/bin の symlink は (無ければ) 補修される。
            self.assertTrue((root / ".local/bin/go").is_symlink())

    def test_go_version_probes_force_local_toolchain_from_neutral_cwd(self) -> None:
        version = self.data["go"]["version"]
        for path in ("installed", "candidate"):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                if path == "installed":
                    final_root = root / ".local/share/chezmoi-dotfiles/go"
                    self._write_go_fixture(
                        final_root, version, require_local_probe=True
                    )
                    source = _render(GO_SH, "linux", "amd64")
                    env = self._stub_curl(root, None)
                    env["STUB_CURL_MUST_NOT_RUN"] = "1"
                else:
                    archive = self._go_archive(
                        version, require_local_probe=True
                    )
                    body = root / "download.bin"
                    body.write_bytes(archive)
                    source = _render(GO_SH, "linux", "amd64").replace(
                        self.data["go"]["assets"]["linux-amd64"]["sha256"],
                        _sha256_bytes(archive),
                    )
                    env = self._stub_curl(root, body)
                env["GOTOOLCHAIN"] = "auto"
                env["GOWORK"] = _shell_path(root / "foreign-go.work")

                result = self._run_script(source, root, env)

                self.assertEqual(result.returncode, 0, result.stderr)

    def test_go_repairs_missing_local_bin_symlink_without_downloading(self) -> None:
        """payload が完全なら、~/.local/bin の symlink 欠落だけを再ダウンロード無しで直す。"""
        version = self.data["go"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = root / ".local/share/chezmoi-dotfiles/go"
            self._write_go_fixture(final_root, version)
            # symlink は意図的に欠落させたまま (削除されたと想定)。
            env = self._stub_curl(root, None)
            env["STUB_CURL_MUST_NOT_RUN"] = "1"

            result = self._run_script(_render(GO_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            local_bin_go = root / ".local/bin/go"
            self.assertTrue(local_bin_go.is_symlink())
            self.assertEqual(local_bin_go.resolve(), (final_root / "bin/go").resolve())

    def test_go_download_failure_returns_nonzero_and_keeps_existing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            entrypoint = root / ".local/share/chezmoi-dotfiles/go/bin/go"
            _write_executable(
                entrypoint, "#!/bin/sh\necho 'go version go1.20.0 linux/amd64'\n"
            )
            original = entrypoint.read_text(encoding="utf-8")
            env = self._stub_curl(root, None)  # body=None -> curl exits 22 (failure)

            result = self._run_script(_render(GO_SH, "linux", "amd64"), root, env)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("failed to download", result.stderr)
            self.assertEqual(entrypoint.read_text(encoding="utf-8"), original)

    def test_go_stale_mise_shim_link_is_replaced_not_left_dangling(self) -> None:
        """旧 mise shim への symlink は安全に置き換える (証拠: shim ディレクトリ配下)。"""
        version = self.data["go"]["version"]
        archive = self._go_archive(version)
        asset_sha256 = _sha256_bytes(archive)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            body = root / "download.bin"
            body.write_bytes(archive)
            source = _render(GO_SH, "linux", "amd64").replace(
                self.data["go"]["assets"]["linux-amd64"]["sha256"], asset_sha256
            )
            env = self._stub_curl(root, body)

            # 旧 mise shim を模した symlink を ~/.local/bin/go に置いておく。
            mise_shim = root / ".local/share/mise/shims/go"
            _write_executable(mise_shim, "#!/bin/sh\necho stale-mise-go\n")
            local_bin = root / ".local/bin"
            local_bin.mkdir(parents=True)
            (local_bin / "go").symlink_to(mise_shim)

            result = self._run_script(source, root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (local_bin / "go").resolve(),
                (root / ".local/share/chezmoi-dotfiles/go/bin/go").resolve(),
            )

    def test_go_does_not_clobber_unrelated_local_bin_entry(self) -> None:
        """管理対象外の file/link は nonzero とし、完全な payload にも触らない。"""
        version = self.data["go"]["version"]
        for kind in ("file", "unrelated-link", "wrong-mise-name"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                final_root = root / ".local/share/chezmoi-dotfiles/go"
                self._write_go_fixture(final_root, version)
                original = (final_root / "bin/go").read_bytes()
                local_bin = root / ".local/bin"
                if kind == "file":
                    _write_executable(
                        local_bin / "go", "#!/bin/sh\necho user-managed-go\n"
                    )
                else:
                    foreign = (
                        root / ".local/share/mise/shims/gofmt"
                        if kind == "wrong-mise-name"
                        else root / "user-tools/go"
                    )
                    _write_executable(foreign, "#!/bin/sh\necho foreign-go\n")
                    local_bin.mkdir(parents=True, exist_ok=True)
                    (local_bin / "go").symlink_to(foreign)
                link_before = (
                    os.readlink(local_bin / "go")
                    if (local_bin / "go").is_symlink()
                    else (local_bin / "go").read_text(encoding="utf-8")
                )
                env = self._stub_curl(root, None)
                env["STUB_CURL_MUST_NOT_RUN"] = "1"

                result = self._run_script(
                    _render(GO_SH, "linux", "amd64"), root, env
                )

                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("refusing to replace it", result.stderr)
                self.assertEqual((final_root / "bin/go").read_bytes(), original)
                link_after = (
                    os.readlink(local_bin / "go")
                    if (local_bin / "go").is_symlink()
                    else (local_bin / "go").read_text(encoding="utf-8")
                )
                self.assertEqual(link_after, link_before)

    def test_go_preserves_foreign_literal_tmp_file(self) -> None:
        version = self.data["go"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = root / ".local/share/chezmoi-dotfiles/go"
            self._write_go_fixture(final_root, version)
            marker = root / ".local/bin/go.tmp"
            marker.parent.mkdir(parents=True)
            marker.write_text("foreign-marker\n", encoding="utf-8")
            env = self._stub_curl(root, None)
            env["STUB_CURL_MUST_NOT_RUN"] = "1"

            result = self._run_script(_render(GO_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "foreign-marker\n")

    def test_go_unrelated_entrypoint_blocks_payload_replacement(self) -> None:
        version = self.data["go"]["version"]
        archive = self._go_archive(version)
        asset_sha256 = _sha256_bytes(archive)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            body = root / "download.bin"
            body.write_bytes(archive)
            source = _render(GO_SH, "linux", "amd64").replace(
                self.data["go"]["assets"]["linux-amd64"]["sha256"], asset_sha256
            )
            final_root = root / ".local/share/chezmoi-dotfiles/go"
            self._write_go_fixture(final_root, "1.20.0")
            old_payload = (final_root / "bin/go").read_bytes()
            _write_executable(
                root / ".local/bin/go", "#!/bin/sh\necho user-managed-go\n"
            )
            env = self._stub_curl(root, body)

            result = self._run_script(source, root, env)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual((final_root / "bin/go").read_bytes(), old_payload)
            self.assertFalse((root / ".local/bin/go").is_symlink())

    def test_go_second_entrypoint_failure_restores_payload_and_links_then_retries(
        self,
    ) -> None:
        version = self.data["go"]["version"]
        archive = self._go_archive(version)
        asset_sha256 = _sha256_bytes(archive)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            body = root / "download.bin"
            body.write_bytes(archive)
            source = _render(GO_SH, "linux", "amd64").replace(
                self.data["go"]["assets"]["linux-amd64"]["sha256"], asset_sha256
            )
            old_version = "1.20.0"
            final_root = root / ".local/share/chezmoi-dotfiles/go"
            self._write_go_fixture(final_root, old_version)
            old_payload = (final_root / "bin/go").read_bytes()
            local_bin = root / ".local/bin"
            old_links: dict[str, str] = {}
            for name in ("go", "gofmt"):
                shim = root / ".local/share/mise/shims" / name
                _write_executable(shim, f"#!/bin/sh\necho stale-{name}\n")
                local_bin.mkdir(parents=True, exist_ok=True)
                (local_bin / name).symlink_to(shim)
                old_links[name] = os.readlink(local_bin / name)
            env = self._stub_curl(root, body)
            self._stub_go_second_entrypoint_publish_failure(root, env)

            failed = self._run_script(source, root, env)

            self.assertNotEqual(failed.returncode, 0, failed.stdout)
            self.assertEqual((final_root / "bin/go").read_bytes(), old_payload)
            for name, target in old_links.items():
                self.assertTrue((local_bin / name).is_symlink())
                self.assertEqual(os.readlink(local_bin / name), target)

            (root / "stub-bin/mv").unlink()
            retried = self._run_script(source, root, env)

            self.assertEqual(retried.returncode, 0, retried.stderr)
            self.assertIn(
                version, (final_root / "bin/go").read_text(encoding="utf-8")
            )
            for name in ("go", "gofmt"):
                self.assertEqual(
                    (local_bin / name).resolve(), (final_root / "bin" / name).resolve()
                )

    def test_go_repair_failure_restores_both_links_without_downloading(self) -> None:
        version = self.data["go"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = root / ".local/share/chezmoi-dotfiles/go"
            self._write_go_fixture(final_root, version)
            old_payload = (final_root / "bin/go").read_bytes()
            local_bin = root / ".local/bin"
            old_links: dict[str, str] = {}
            for name in ("go", "gofmt"):
                shim = root / ".local/share/mise/shims" / name
                _write_executable(shim, f"#!/bin/sh\necho stale-{name}\n")
                local_bin.mkdir(parents=True, exist_ok=True)
                (local_bin / name).symlink_to(shim)
                old_links[name] = os.readlink(local_bin / name)
            env = self._stub_curl(root, None)
            env["STUB_CURL_MUST_NOT_RUN"] = "1"
            self._stub_go_second_entrypoint_publish_failure(root, env)

            result = self._run_script(_render(GO_SH, "linux", "amd64"), root, env)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual((final_root / "bin/go").read_bytes(), old_payload)
            for name, target in old_links.items():
                self.assertTrue((local_bin / name).is_symlink())
                self.assertEqual(os.readlink(local_bin / name), target)

    def test_go_second_entrypoint_failure_leaves_fresh_install_absent(self) -> None:
        version = self.data["go"]["version"]
        archive = self._go_archive(version)
        asset_sha256 = _sha256_bytes(archive)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            body = root / "download.bin"
            body.write_bytes(archive)
            source = _render(GO_SH, "linux", "amd64").replace(
                self.data["go"]["assets"]["linux-amd64"]["sha256"], asset_sha256
            )
            env = self._stub_curl(root, body)
            self._stub_go_second_entrypoint_publish_failure(root, env)

            failed = self._run_script(source, root, env)

            self.assertNotEqual(failed.returncode, 0, failed.stdout)
            self.assertFalse(
                (root / ".local/share/chezmoi-dotfiles/go").exists()
            )
            self.assertFalse(os.path.lexists(root / ".local/bin/go"))
            self.assertFalse(os.path.lexists(root / ".local/bin/gofmt"))

    def test_go_checksum_failure_keeps_the_existing_installation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            entrypoint = root / ".local/share/chezmoi-dotfiles/go/bin/go"
            _write_executable(
                entrypoint, "#!/bin/sh\necho 'go version go1.20.0 linux/amd64'\n"
            )
            original = entrypoint.read_text(encoding="utf-8")
            body = root / "download.bin"
            body.write_text("not the official asset", encoding="utf-8")
            env = self._stub_curl(root, body)

            result = self._run_script(_render(GO_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("checksum verification failed", result.stderr)
            self.assertEqual(entrypoint.read_text(encoding="utf-8"), original)

    def test_node_fresh_install_extracts_and_verifies_the_entrypoint(self) -> None:
        version = self.data["node"]["version"]
        archive = self._node_archive(version)
        asset_sha256 = _sha256_bytes(archive)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            body = root / "download.bin"
            body.write_bytes(archive)
            source = _render(NODE_SH, "linux", "amd64").replace(
                self.data["node"]["assets"]["linux-amd64"]["sha256"], asset_sha256
            )
            env = self._stub_curl(root, body)

            result = self._run_script(source, root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            final_root = root / ".local/share/chezmoi-dotfiles/node"
            entrypoint = final_root / "bin/node"
            self.assertTrue(entrypoint.is_file())
            check = subprocess.run(
                [str(entrypoint), "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(check.stdout.strip(), f"v{version}")
            # ~/.local/bin へ node/npm/npx の native symlink も同時に発行される。
            for name in ("node", "npm", "npx"):
                link = root / ".local/bin" / name
                self.assertTrue(link.is_symlink(), f"{name} should be a symlink")
                self.assertEqual(link.resolve(), (final_root / "bin" / name).resolve())

    def test_node_version_mismatch_keeps_the_existing_installation(self) -> None:
        """checksum を通った成果物でも、版が宣言と違えば置き換えない。"""
        version = self.data["node"]["version"]
        archive = self._node_archive("20.0.0")
        asset_sha256 = _sha256_bytes(archive)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            entrypoint = root / ".local/share/chezmoi-dotfiles/node/bin/node"
            _write_executable(entrypoint, "#!/bin/sh\necho 'v23.0.0'\n")
            original = entrypoint.read_text(encoding="utf-8")
            body = root / "download.bin"
            body.write_bytes(archive)
            source = _render(NODE_SH, "linux", "amd64").replace(
                self.data["node"]["assets"]["linux-amd64"]["sha256"], asset_sha256
            )
            env = self._stub_curl(root, body)

            result = self._run_script(source, root, env)

            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn(f"expected node {version}", result.stderr)
            self.assertIn("20.0.0", result.stderr)
            self.assertEqual(entrypoint.read_text(encoding="utf-8"), original)

    def test_node_download_failure_returns_nonzero_and_keeps_existing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            entrypoint = root / ".local/share/chezmoi-dotfiles/node/bin/node"
            _write_executable(entrypoint, "#!/bin/sh\necho 'v20.0.0'\n")
            original = entrypoint.read_text(encoding="utf-8")
            env = self._stub_curl(root, None)  # body=None -> curl exits 22 (failure)

            result = self._run_script(_render(NODE_SH, "linux", "amd64"), root, env)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("failed to download", result.stderr)
            self.assertEqual(entrypoint.read_text(encoding="utf-8"), original)

    def test_node_repairs_missing_local_bin_symlinks_without_downloading(self) -> None:
        """payload が完全なら、~/.local/bin の symlink 欠落だけを再ダウンロード無しで直す。"""
        version = self.data["node"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = root / ".local/share/chezmoi-dotfiles/node"
            _write_executable(final_root / "bin/node", f"#!/bin/sh\necho 'v{version}'\n")
            _write_executable(final_root / "bin/npm", "#!/bin/sh\necho npm-stub\n")
            _write_executable(final_root / "bin/npx", "#!/bin/sh\necho npx-stub\n")
            (final_root / "lib/node_modules/npm/bin").mkdir(parents=True)
            (final_root / "lib/node_modules/npm/bin/npm-cli.js").write_text("// stub\n")
            (final_root / "lib/node_modules/npm/bin/npx-cli.js").write_text("// stub\n")
            (final_root / "lib/node_modules/npm/package.json").write_text('{"name":"npm"}\n')
            # symlink は意図的に欠落させたまま (削除されたと想定)。
            env = self._stub_curl(root, None)
            env["STUB_CURL_MUST_NOT_RUN"] = "1"

            result = self._run_script(_render(NODE_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("node", "npm", "npx"):
                link = root / ".local/bin" / name
                self.assertTrue(link.is_symlink(), f"{name} should be a symlink")
                self.assertEqual(link.resolve(), (final_root / "bin" / name).resolve())

    def test_node_stale_mise_shim_link_is_replaced_not_left_dangling(self) -> None:
        """旧 mise shim への symlink は安全に置き換える (証拠: shim ディレクトリ配下)。"""
        version = self.data["node"]["version"]
        archive = self._node_archive(version)
        asset_sha256 = _sha256_bytes(archive)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            body = root / "download.bin"
            body.write_bytes(archive)
            source = _render(NODE_SH, "linux", "amd64").replace(
                self.data["node"]["assets"]["linux-amd64"]["sha256"], asset_sha256
            )
            env = self._stub_curl(root, body)

            mise_shim = root / ".local/share/mise/shims/npm"
            _write_executable(mise_shim, "#!/bin/sh\necho stale-mise-npm\n")
            local_bin = root / ".local/bin"
            local_bin.mkdir(parents=True)
            (local_bin / "npm").symlink_to(mise_shim)

            result = self._run_script(source, root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (local_bin / "npm").resolve(),
                (root / ".local/share/chezmoi-dotfiles/node/bin/npm").resolve(),
            )

    def test_dotnet_fresh_install_verifies_sdk_directory_presence(self) -> None:
        version = self.data["dotnet"]["version"]
        archive = self._dotnet_archive(version)
        asset_sha512 = _sha512_bytes(archive)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            body = root / "download.bin"
            body.write_bytes(archive)
            source = _render(DOTNET_SH, "linux", "amd64").replace(
                self.data["dotnet"]["assets"]["linux-amd64"]["sha512"], asset_sha512
            )
            env = self._stub_curl(root, body)

            result = self._run_script(source, root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            final_root = root / ".local/share/chezmoi-dotfiles/dotnet"
            self.assertTrue((final_root / "dotnet").is_file())
            self.assertTrue((final_root / "dnx").is_file())
            self.assertTrue((final_root / "sdk" / version).is_dir())
            self.assertTrue((final_root / "sdk" / version / "dotnet.dll").is_file())
            self.assertTrue(
                (
                    final_root
                    / "sdk"
                    / version
                    / "Sdks/Microsoft.NET.Sdk/Sdk/Sdk.props"
                ).is_file()
            )
            # ~/.local/bin へ dotnet/dnx の native symlink も同時に発行される。
            for name in ("dotnet", "dnx"):
                link = root / ".local/bin" / name
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), (final_root / name).resolve())

    def test_dotnet_candidate_without_dnx_keeps_the_existing_installation(
        self,
    ) -> None:
        version = self.data["dotnet"]["version"]
        archive = self._dotnet_archive(version, include_dnx=False)
        asset_sha512 = _sha512_bytes(archive)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = root / ".local/share/chezmoi-dotfiles/dotnet"
            self._write_dotnet_fixture(final_root, "9.0.100")
            old_dotnet = (final_root / "dotnet").read_bytes()
            old_dnx = (final_root / "dnx").read_bytes()
            body = root / "download.bin"
            body.write_bytes(archive)
            source = _render(DOTNET_SH, "linux", "amd64").replace(
                self.data["dotnet"]["assets"]["linux-amd64"]["sha512"],
                asset_sha512,
            )
            env = self._stub_curl(root, body)

            result = self._run_script(source, root, env)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("expected dotnet, dnx", result.stderr)
            self.assertEqual((final_root / "dotnet").read_bytes(), old_dotnet)
            self.assertEqual((final_root / "dnx").read_bytes(), old_dnx)

    def test_dotnet_does_not_set_dotnet_root_or_touch_other_sdks(self) -> None:
        """他が所有する .NET SDK と衝突しないよう DOTNET_ROOT を設定しない。

        設計意図を説明するコメント中の言及は許容し、実際に環境変数として
        代入 (`DOTNET_ROOT=...`) または export しているかどうかだけを見る。
        """
        source = DOTNET_SH.read_text(encoding="utf-8")

        self.assertNotRegex(source, r"(?m)^\s*export\s+DOTNET_ROOT\b")
        self.assertNotRegex(source, r"(?m)^\s*DOTNET_ROOT\s*=")

    def test_dotnet_checksum_failure_keeps_the_existing_installation(self) -> None:
        version = self.data["dotnet"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = root / ".local/share/chezmoi-dotfiles/dotnet"
            self._write_dotnet_fixture(final_root, version)
            body = root / "download.bin"
            body.write_text("not the official asset", encoding="utf-8")
            env = self._stub_curl(root, body)

            # 既存の版と宣言が同じままだと "既に導入済み" 早期 return を通って
            # しまうため、宣言側の版を意図的に変えて検証経路まで進める。
            source = _render(DOTNET_SH, "linux", "amd64").replace(
                f"dotnet_version='{version}'", "dotnet_version='99.0.100'"
            )
            result = self._run_script(source, root, env)

            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("checksum verification failed", result.stderr)
            self.assertTrue((final_root / "sdk" / version).is_dir())

    def test_dotnet_download_failure_returns_nonzero_and_keeps_existing(self) -> None:
        version = self.data["dotnet"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = root / ".local/share/chezmoi-dotfiles/dotnet"
            self._write_dotnet_fixture(final_root, version)
            env = self._stub_curl(root, None)  # body=None -> curl exits 22 (failure)

            source = _render(DOTNET_SH, "linux", "amd64").replace(
                f"dotnet_version='{version}'", "dotnet_version='99.0.100'"
            )
            result = self._run_script(source, root, env)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("failed to download", result.stderr)
            self.assertTrue((final_root / "sdk" / version).is_dir())

    def test_dotnet_repairs_missing_dnx_link_without_downloading(self) -> None:
        version = self.data["dotnet"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = root / ".local/share/chezmoi-dotfiles/dotnet"
            self._write_dotnet_fixture(final_root, version)
            local_bin = root / ".local/bin"
            local_bin.mkdir(parents=True)
            (local_bin / "dotnet").symlink_to(final_root / "dotnet")
            env = self._stub_curl(root, None)
            env["STUB_CURL_MUST_NOT_RUN"] = "1"

            result = self._run_script(_render(DOTNET_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((local_bin / "dotnet").resolve(), (final_root / "dotnet").resolve())
            self.assertTrue((local_bin / "dnx").is_symlink())
            self.assertEqual((local_bin / "dnx").resolve(), (final_root / "dnx").resolve())

    def test_dotnet_second_entrypoint_failure_restores_payload_and_links(self) -> None:
        version = self.data["dotnet"]["version"]
        archive = self._dotnet_archive(version)
        asset_sha512 = _sha512_bytes(archive)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            body = root / "download.bin"
            body.write_bytes(archive)
            source = _render(DOTNET_SH, "linux", "amd64").replace(
                self.data["dotnet"]["assets"]["linux-amd64"]["sha512"],
                asset_sha512,
            )
            final_root = root / ".local/share/chezmoi-dotfiles/dotnet"
            self._write_dotnet_fixture(final_root, "9.0.100")
            old_dotnet = (final_root / "dotnet").read_bytes()
            old_dnx = (final_root / "dnx").read_bytes()
            local_bin = root / ".local/bin"
            old_links: dict[str, str] = {}
            for name in ("dotnet", "dnx"):
                shim = root / ".local/share/mise/shims" / name
                _write_executable(shim, f"#!/bin/sh\necho stale-{name}\n")
                local_bin.mkdir(parents=True, exist_ok=True)
                (local_bin / name).symlink_to(shim)
                old_links[name] = os.readlink(local_bin / name)
            env = self._stub_curl(root, body)
            self._stub_dotnet_second_entrypoint_publish_failure(root, env)

            result = self._run_script(source, root, env)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual((final_root / "dotnet").read_bytes(), old_dotnet)
            self.assertEqual((final_root / "dnx").read_bytes(), old_dnx)
            for name, target in old_links.items():
                self.assertTrue((local_bin / name).is_symlink())
                self.assertEqual(os.readlink(local_bin / name), target)

    def test_bun_fresh_install_places_a_single_executable_in_local_bin(self) -> None:
        version = self.data["bun"]["version"]
        archive = _make_zip(
            {"bun-linux-x64/bun": f"#!/bin/sh\necho '{version}'\n"},
            {"bun-linux-x64/bun"},
        )
        asset_sha256 = _sha256_bytes(archive)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            body = root / "download.bin"
            body.write_bytes(archive)
            source = _render(BUN_SH, "linux", "amd64").replace(
                self.data["bun"]["assets"]["linux-amd64"]["sha256"], asset_sha256
            )
            env = self._stub_curl(root, body)
            if shutil.which("unzip") is None:
                self.skipTest("unzip is required for bun install tests")

            result = self._run_script(source, root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            entrypoint = root / ".local/bin/bun"
            self.assertTrue(entrypoint.is_file())
            check = subprocess.run(
                [str(entrypoint), "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(check.stdout.strip(), version)
            # bunx は bun への直接 symlink (公式の argv0 分岐に乗る、副作用の無い
            # completions 非実行版)。
            bunx = root / ".local/bin/bunx"
            self.assertTrue(bunx.is_symlink())
            self.assertEqual(bunx.resolve(), entrypoint.resolve())

    def test_bun_checksum_failure_keeps_the_existing_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            entrypoint = root / ".local/bin/bun"
            _write_executable(entrypoint, "#!/bin/sh\necho '1.0.0'\n")
            original = entrypoint.read_text(encoding="utf-8")
            body = root / "download.bin"
            body.write_text("not the official asset", encoding="utf-8")
            env = self._stub_curl(root, body)

            result = self._run_script(_render(BUN_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("checksum verification failed", result.stderr)
            self.assertEqual(entrypoint.read_text(encoding="utf-8"), original)

    def test_bun_download_failure_returns_nonzero_and_keeps_existing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            entrypoint = root / ".local/bin/bun"
            _write_executable(entrypoint, "#!/bin/sh\necho '1.0.0'\n")
            original = entrypoint.read_text(encoding="utf-8")
            env = self._stub_curl(root, None)  # body=None -> curl exits 22 (failure)

            result = self._run_script(_render(BUN_SH, "linux", "amd64"), root, env)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("failed to download", result.stderr)
            self.assertEqual(entrypoint.read_text(encoding="utf-8"), original)

    def test_bun_repairs_missing_bunx_link_without_downloading(self) -> None:
        version = self.data["bun"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            entrypoint = root / ".local/bin/bun"
            _write_executable(entrypoint, f"#!/bin/sh\necho '{version}'\n")
            # bunx は意図的に欠落させたまま。
            env = self._stub_curl(root, None)
            env["STUB_CURL_MUST_NOT_RUN"] = "1"

            result = self._run_script(_render(BUN_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            bunx = root / ".local/bin/bunx"
            self.assertTrue(bunx.is_symlink())
            self.assertEqual(bunx.resolve(), entrypoint.resolve())

    def test_pnpm_fresh_install_keeps_the_flat_archive_layout(self) -> None:
        version = self.data["pnpm"]["version"]
        archive = self._pnpm_archive(version)
        asset_sha256 = _sha256_bytes(archive)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            body = root / "download.bin"
            body.write_bytes(archive)
            source = _render(PNPM_SH, "linux", "amd64").replace(
                self.data["pnpm"]["assets"]["linux-amd64"]["sha256"], asset_sha256
            )
            env = self._stub_curl(root, body)

            result = self._run_script(source, root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            final_root = root / ".local/share/chezmoi-dotfiles/pnpm"
            entrypoint = final_root / "pnpm"
            self.assertTrue(entrypoint.is_file())
            self.assertTrue((final_root / "dist/pnpm.mjs").is_file())
            self.assertTrue((final_root / "dist/worker.js").is_file())
            check = subprocess.run(
                [str(entrypoint), "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(check.stdout.strip(), version)
            # ~/.local/bin/pnpm の native symlink も同時に発行される。
            link = root / ".local/bin/pnpm"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), entrypoint.resolve())

    def test_pnpm_version_probes_disable_project_toolchain_switching(self) -> None:
        version = self.data["pnpm"]["version"]
        for path in ("installed", "candidate"):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                if path == "installed":
                    final_root = root / ".local/share/chezmoi-dotfiles/pnpm"
                    self._write_pnpm_fixture(
                        final_root, version, require_offline_probe=True
                    )
                    source = _render(PNPM_SH, "linux", "amd64")
                    env = self._stub_curl(root, None)
                    env["STUB_CURL_MUST_NOT_RUN"] = "1"
                else:
                    archive = self._pnpm_archive(
                        version, require_offline_probe=True
                    )
                    body = root / "download.bin"
                    body.write_bytes(archive)
                    source = _render(PNPM_SH, "linux", "amd64").replace(
                        self.data["pnpm"]["assets"]["linux-amd64"]["sha256"],
                        _sha256_bytes(archive),
                    )
                    env = self._stub_curl(root, body)
                env["PNPM_CONFIG_PM_ON_FAIL"] = "download"

                result = self._run_script(source, root, env)

                self.assertEqual(result.returncode, 0, result.stderr)

    def test_pnpm_checksum_failure_keeps_the_existing_installation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = root / ".local/share/chezmoi-dotfiles/pnpm"
            _write_executable(final_root / "pnpm", "#!/bin/sh\necho '1.0.0'\n")
            original = (final_root / "pnpm").read_text(encoding="utf-8")
            body = root / "download.bin"
            body.write_text("not the official asset", encoding="utf-8")
            env = self._stub_curl(root, body)

            result = self._run_script(_render(PNPM_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("checksum verification failed", result.stderr)
            self.assertEqual((final_root / "pnpm").read_text(encoding="utf-8"), original)

    def test_pnpm_download_failure_returns_nonzero_and_keeps_existing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = root / ".local/share/chezmoi-dotfiles/pnpm"
            _write_executable(final_root / "pnpm", "#!/bin/sh\necho '1.0.0'\n")
            original = (final_root / "pnpm").read_text(encoding="utf-8")
            env = self._stub_curl(root, None)  # body=None -> curl exits 22 (failure)

            result = self._run_script(_render(PNPM_SH, "linux", "amd64"), root, env)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("failed to download", result.stderr)
            self.assertEqual((final_root / "pnpm").read_text(encoding="utf-8"), original)

    def test_pnpm_repairs_missing_local_bin_symlink_without_downloading(self) -> None:
        version = self.data["pnpm"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = root / ".local/share/chezmoi-dotfiles/pnpm"
            _write_executable(final_root / "pnpm", f"#!/bin/sh\necho '{version}'\n")
            (final_root / "dist").mkdir(parents=True)
            (final_root / "dist/pnpm.mjs").write_text("// stub\n")
            (final_root / "dist/worker.js").write_text("// stub\n")
            # symlink は意図的に欠落させたまま。
            env = self._stub_curl(root, None)
            env["STUB_CURL_MUST_NOT_RUN"] = "1"

            result = self._run_script(_render(PNPM_SH, "linux", "amd64"), root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            link = root / ".local/bin/pnpm"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), (final_root / "pnpm").resolve())


class NpmBasedInstallBehaviourTests(unittest.TestCase):
    """TypeScript CLI / typescript-lsp / typescript-language-server 用。

    直接導入した Node/npm の代わりに、決定的な stub node/npm を使って
    staging → 検証 → atomic swap 経路だけを確認する。
    """

    @classmethod
    def setUpClass(cls) -> None:
        if BASH is None:
            raise unittest.SkipTest("bash is required for direct-install tests")
        cls.data = _load_data()

    NODE_STUB = (
        "#!/bin/sh\n"
        "case \"${1:-}\" in\n"
        "  */npm-cli.js)\n"
        "    shift\n"
        "    exec \"${0%/*}/npm\" \"$@\"\n"
        "    ;;\n"
        "esac\n"
        "if [ \"$1\" = \"-p\" ]; then\n"
        "  pkg=\"$3\"\n"
        "  awk -F'\"' '{for (i = 1; i <= NF; i++) if ($i == \"version\") "
        "{print $(i + 2); exit}}' \"$pkg\"\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${2:-}\" = \"--version\" ] && [ -f \"${1:-}\" ]; then\n"
        "  version=\"\"\n"
        "  while IFS= read -r line; do\n"
        "    case \"$line\" in\n"
        "      '// MOCK_VERSION='*) version=\"${line#// MOCK_VERSION=}\" ;;\n"
        "    esac\n"
        "  done < \"$1\"\n"
        "  [ -n \"$version\" ] || exit 1\n"
        "  case \"${1##*/}\" in\n"
        "    tsc) printf 'Version %s\\n' \"$version\" ;;\n"
        "    typescript-language-server) printf '%s\\n' \"$version\" ;;\n"
        "    *) exit 1 ;;\n"
        "  esac\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    )

    def _write_node_stubs(self, root: pathlib.Path) -> None:
        node_root = root / ".local/share/chezmoi-dotfiles/node"
        _write_executable(node_root / "bin/node", self.NODE_STUB)
        _write_executable(node_root / "bin/npm", "#!/bin/sh\nexit 1\n")
        npm_cli_js = node_root / "lib/node_modules/npm/bin/npm-cli.js"
        npm_cli_js.parent.mkdir(parents=True)
        npm_cli_js.write_text("// npm CLI fixture\n", encoding="utf-8")

    def _write_mock_node_launcher(
        self, path: pathlib.Path, version: str
    ) -> None:
        _write_executable(
            path,
            f"#!/usr/bin/env node\n// MOCK_VERSION={version}\n",
        )

    def _npm_stub(
        self,
        *,
        succeed: bool,
        package_name: str,
        version: str,
        bin_name: str,
        launcher_version: str | None = None,
        extra_files: dict[str, str] | None = None,
    ) -> str:
        """npm install --prefix <dir> --no-save --package-lock=false <spec>."""
        extra = ""
        for relpath, content in (extra_files or {}).items():
            extra += (
                f'mkdir -p "$prefix/node_modules/{package_name}/$(dirname {relpath})"\n'
                if "/" in relpath
                else ""
            )
            extra += (
                f'printf %s {json.dumps(content)} '
                f'> "$prefix/node_modules/{package_name}/{relpath}"\n'
            )
        body = (
            "#!/bin/sh\n"
            "prefix=\"\"\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "  case \"$1\" in\n"
            "    --prefix) prefix=\"$2\"; shift 2 ;;\n"
            "    *) shift ;;\n"
            "  esac\n"
            "done\n"
        )
        if not succeed:
            return body + "exit 1\n"
        if launcher_version is None:
            launcher_version = version
        body += (
            f'mkdir -p "$prefix/node_modules/{package_name}" "$prefix/node_modules/.bin"\n'
            f'printf \'{{"name":"{package_name}","version":"{version}"}}\' '
            f'> "$prefix/node_modules/{package_name}/package.json"\n'
            f"{extra}"
            f"printf '#!/usr/bin/env node\\n// MOCK_VERSION={launcher_version}\\n' "
            f'> "$prefix/node_modules/.bin/{bin_name}"\n'
            f'chmod 755 "$prefix/node_modules/.bin/{bin_name}"\n'
        )
        return body

    def _run_script(
        self,
        sh_path: pathlib.Path,
        root: pathlib.Path,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        script = root / "rendered-installer.sh"
        script.write_text(_render(sh_path, "linux", "amd64"), encoding="utf-8")
        env = dict(os.environ)
        env["HOME"] = _shell_path(root)
        env.update(extra_env or {})
        return subprocess.run(
            [BASH, _shell_path(script)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_npm_install_uses_absolute_private_node_with_poisoned_path(
        self,
    ) -> None:
        cases = (
            (
                TS_CLI_SH,
                "typescript",
                self.data["typescriptCli"]["version"],
                "tsc",
                None,
            ),
            (
                TS_LSP_SH,
                "typescript",
                self.data["typescriptLsp"]["version"],
                "tsserver",
                {"lib/tsserver.js": "// stub tsserver\n"},
            ),
            (
                TSLS_SH,
                "typescript-language-server",
                self.data["typescriptLanguageServer"]["version"],
                "typescript-language-server",
                None,
            ),
        )
        for sh_path, package_name, version, bin_name, extra_files in cases:
            with self.subTest(installer=sh_path.name), tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                self._write_node_stubs(root)
                node_root = root / ".local/share/chezmoi-dotfiles/node"
                _write_executable(
                    node_root / "bin/npm",
                    self._npm_stub(
                        succeed=True,
                        package_name=package_name,
                        version=version,
                        bin_name=bin_name,
                        extra_files=extra_files,
                    ),
                )
                poison_dir = root / ".local/share/mise/shims"
                poison_marker = root / "poison-node-used"
                _write_executable(
                    poison_dir / "node",
                    "#!/bin/sh\n"
                    'printf poison > "$POISON_NODE_MARKER"\n'
                    "exit 97\n",
                )
                system_path = os.pathsep.join(
                    part
                    for part in os.environ["PATH"].split(os.pathsep)
                    if "/.local/bin" not in pathlib.Path(part).as_posix()
                )
                env = {
                    "PATH": f"{poison_dir}{os.pathsep}{system_path}",
                    "POISON_NODE_MARKER": _shell_path(poison_marker),
                }

                result = self._run_script(sh_path, root, env)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(poison_marker.exists())

    def test_npm_consumers_require_the_private_npm_cli_module(self) -> None:
        for sh_path in (TS_CLI_SH, TS_LSP_SH, TSLS_SH):
            with self.subTest(installer=sh_path.name), tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                self._write_node_stubs(root)
                (
                    root
                    / ".local/share/chezmoi-dotfiles/node/lib/node_modules/npm/bin/npm-cli.js"
                ).unlink()

                result = self._run_script(sh_path, root)

                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("npm CLI was not found", result.stderr)

    def test_cli_launchers_are_executed_for_installed_and_candidate_validation(
        self,
    ) -> None:
        cases = (
            (
                TS_CLI_SH,
                "typescript",
                self.data["typescriptCli"]["version"],
                "tsc",
                "typescript-cli",
            ),
            (
                TSLS_SH,
                "typescript-language-server",
                self.data["typescriptLanguageServer"]["version"],
                "typescript-language-server",
                "typescript-language-server",
            ),
        )
        for sh_path, package_name, version, bin_name, root_name in cases:
            for broken_path in ("installed", "candidate"):
                with (
                    self.subTest(installer=sh_path.name, broken=broken_path),
                    tempfile.TemporaryDirectory() as temp_dir,
                ):
                    root = pathlib.Path(temp_dir)
                    self._write_node_stubs(root)
                    node_root = root / ".local/share/chezmoi-dotfiles/node"
                    final_root = root / ".local/share/chezmoi-dotfiles" / root_name
                    package_dir = final_root / "node_modules" / package_name
                    package_dir.mkdir(parents=True)
                    old_version = version if broken_path == "installed" else "1.0.0"
                    package_path = package_dir / "package.json"
                    package_path.write_text(
                        f'{{"name":"{package_name}","version":"{old_version}"}}',
                        encoding="utf-8",
                    )
                    launcher = final_root / "node_modules/.bin" / bin_name
                    self._write_mock_node_launcher(
                        launcher,
                        "0.0.0" if broken_path == "installed" else old_version,
                    )
                    old_package = package_path.read_bytes()
                    old_launcher = launcher.read_bytes()
                    _write_executable(
                        node_root / "bin/npm",
                        self._npm_stub(
                            succeed=broken_path == "candidate",
                            package_name=package_name,
                            version=version,
                            bin_name=bin_name,
                            launcher_version="0.0.0",
                        ),
                    )

                    result = self._run_script(sh_path, root)

                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(package_path.read_bytes(), old_package)
                    self.assertEqual(launcher.read_bytes(), old_launcher)

    def test_typescript_cli_fresh_install_produces_the_tsc_launcher(self) -> None:
        version = self.data["typescriptCli"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            self._write_node_stubs(root)
            node_root = root / ".local/share/chezmoi-dotfiles/node"
            _write_executable(
                node_root / "bin/npm",
                self._npm_stub(
                    succeed=True,
                    package_name="typescript",
                    version=version,
                    bin_name="tsc",
                ),
            )

            result = self._run_script(TS_CLI_SH, root)

            self.assertEqual(result.returncode, 0, result.stderr)
            final_root = root / ".local/share/chezmoi-dotfiles/typescript-cli"
            self.assertTrue(
                (final_root / "node_modules/.bin/tsc").is_file()
            )
            self.assertIn(
                version,
                (
                    final_root / "node_modules/typescript/package.json"
                ).read_text(encoding="utf-8"),
            )
            link = root / ".local/bin/tsc"
            self.assertTrue(link.is_symlink())
            self.assertEqual(
                link.resolve(), (final_root / "node_modules/.bin/tsc").resolve()
            )

    def test_typescript_cli_npm_failure_returns_nonzero_and_keeps_existing(
        self,
    ) -> None:
        """npm install が失敗したら nonzero を返し、既存の TypeScript CLI を保つ。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            self._write_node_stubs(root)
            node_root = root / ".local/share/chezmoi-dotfiles/node"
            _write_executable(
                node_root / "bin/npm",
                self._npm_stub(
                    succeed=False,
                    package_name="typescript",
                    version="0.0.0",
                    bin_name="tsc",
                ),
            )
            final_root = root / ".local/share/chezmoi-dotfiles/typescript-cli"
            _write_executable(
                final_root / "node_modules/.bin/tsc", "#!/bin/sh\necho old\n"
            )
            (final_root / "node_modules/typescript").mkdir(parents=True, exist_ok=True)
            (final_root / "node_modules/typescript/package.json").write_text(
                '{"name":"typescript","version":"1.0.0"}', encoding="utf-8"
            )

            result = self._run_script(TS_CLI_SH, root)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertTrue(
                (final_root / "node_modules/.bin/tsc").is_file(),
                "the existing TypeScript CLI must survive an npm install failure",
            )
            self.assertIn(
                "1.0.0",
                (
                    final_root / "node_modules/typescript/package.json"
                ).read_text(encoding="utf-8"),
            )

    def test_typescript_cli_missing_node_returns_nonzero_and_keeps_existing(
        self,
    ) -> None:
        """直接導入した Node が無い場合は nonzero を返し、既存を保つ (fail-open にしない)。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = root / ".local/share/chezmoi-dotfiles/typescript-cli"
            _write_executable(
                final_root / "node_modules/.bin/tsc", "#!/bin/sh\necho old\n"
            )
            (final_root / "node_modules/typescript").mkdir(parents=True, exist_ok=True)
            (final_root / "node_modules/typescript/package.json").write_text(
                '{"name":"typescript","version":"1.0.0"}', encoding="utf-8"
            )

            result = self._run_script(TS_CLI_SH, root)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("Node", result.stderr)
            self.assertTrue((final_root / "node_modules/.bin/tsc").is_file())

    def test_typescript_cli_repairs_missing_local_bin_symlink_without_downloading(
        self,
    ) -> None:
        """payload が完全なら、~/.local/bin の symlink 欠落だけを再ダウンロード無しで直す。"""
        version = self.data["typescriptCli"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            self._write_node_stubs(root)
            node_root = root / ".local/share/chezmoi-dotfiles/node"
            # npm が呼ばれたら失敗させ、再ダウンロードが起きていないことを検証する。
            _write_executable(node_root / "bin/npm", "#!/bin/sh\nexit 1\n")
            final_root = root / ".local/share/chezmoi-dotfiles/typescript-cli"
            self._write_mock_node_launcher(
                final_root / "node_modules/.bin/tsc", version
            )
            (final_root / "node_modules/typescript").mkdir(parents=True, exist_ok=True)
            (final_root / "node_modules/typescript/package.json").write_text(
                f'{{"name":"typescript","version":"{version}"}}', encoding="utf-8"
            )

            result = self._run_script(TS_CLI_SH, root)

            self.assertEqual(result.returncode, 0, result.stdout)
            link = root / ".local/bin/tsc"
            self.assertTrue(link.is_symlink())
            self.assertEqual(
                link.resolve(), (final_root / "node_modules/.bin/tsc").resolve()
            )

    def test_typescript_lsp_fresh_install_produces_tsserver_js(self) -> None:
        version = self.data["typescriptLsp"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            self._write_node_stubs(root)
            node_root = root / ".local/share/chezmoi-dotfiles/node"
            _write_executable(
                node_root / "bin/npm",
                self._npm_stub(
                    succeed=True,
                    package_name="typescript",
                    version=version,
                    bin_name="tsserver",
                    extra_files={"lib/tsserver.js": "// stub tsserver\n"},
                ),
            )

            result = self._run_script(TS_LSP_SH, root)

            self.assertEqual(result.returncode, 0, result.stderr)
            final_root = root / ".local/share/chezmoi-dotfiles/typescript-lsp"
            self.assertTrue(
                (final_root / "node_modules/typescript/lib/tsserver.js").is_file()
            )
            link = root / ".local/bin/tsserver"
            self.assertTrue(link.is_symlink())
            self.assertEqual(
                link.resolve(),
                (final_root / "node_modules/.bin/tsserver").resolve(),
            )

    def test_typescript_lsp_npm_failure_returns_nonzero_and_keeps_existing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            self._write_node_stubs(root)
            node_root = root / ".local/share/chezmoi-dotfiles/node"
            _write_executable(
                node_root / "bin/npm",
                self._npm_stub(
                    succeed=False,
                    package_name="typescript",
                    version="0.0.0",
                    bin_name="tsserver",
                ),
            )
            final_root = root / ".local/share/chezmoi-dotfiles/typescript-lsp"
            (final_root / "node_modules/typescript/lib").mkdir(
                parents=True, exist_ok=True
            )
            (final_root / "node_modules/typescript/lib/tsserver.js").write_text(
                "// existing tsserver\n", encoding="utf-8"
            )
            (final_root / "node_modules/typescript/package.json").write_text(
                '{"name":"typescript","version":"6.0.3"}', encoding="utf-8"
            )

            result = self._run_script(TS_LSP_SH, root)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertTrue(
                (final_root / "node_modules/typescript/lib/tsserver.js").is_file(),
                "the existing TypeScript LSP dependency must survive an npm "
                "install failure",
            )

    def test_typescript_lsp_missing_node_returns_nonzero_and_keeps_existing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = root / ".local/share/chezmoi-dotfiles/typescript-lsp"
            (final_root / "node_modules/typescript/lib").mkdir(
                parents=True, exist_ok=True
            )
            (final_root / "node_modules/typescript/lib/tsserver.js").write_text(
                "// existing tsserver\n", encoding="utf-8"
            )
            (final_root / "node_modules/typescript/package.json").write_text(
                '{"name":"typescript","version":"6.0.3"}', encoding="utf-8"
            )

            result = self._run_script(TS_LSP_SH, root)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("Node", result.stderr)
            self.assertTrue(
                (final_root / "node_modules/typescript/lib/tsserver.js").is_file()
            )

    def test_typescript_language_server_fresh_install_produces_the_launcher(
        self,
    ) -> None:
        version = self.data["typescriptLanguageServer"]["version"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            self._write_node_stubs(root)
            node_root = root / ".local/share/chezmoi-dotfiles/node"
            _write_executable(
                node_root / "bin/npm",
                self._npm_stub(
                    succeed=True,
                    package_name="typescript-language-server",
                    version=version,
                    bin_name="typescript-language-server",
                ),
            )

            result = self._run_script(TSLS_SH, root)

            self.assertEqual(result.returncode, 0, result.stderr)
            final_root = (
                root / ".local/share/chezmoi-dotfiles/typescript-language-server"
            )
            self.assertTrue(
                (
                    final_root / "node_modules/.bin/typescript-language-server"
                ).is_file()
            )
            link = root / ".local/bin/typescript-language-server"
            self.assertTrue(link.is_symlink())
            self.assertEqual(
                link.resolve(),
                (
                    final_root / "node_modules/.bin/typescript-language-server"
                ).resolve(),
            )

    def test_typescript_language_server_npm_failure_returns_nonzero_and_keeps_existing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            self._write_node_stubs(root)
            node_root = root / ".local/share/chezmoi-dotfiles/node"
            _write_executable(
                node_root / "bin/npm",
                self._npm_stub(
                    succeed=False,
                    package_name="typescript-language-server",
                    version="0.0.0",
                    bin_name="typescript-language-server",
                ),
            )
            final_root = (
                root / ".local/share/chezmoi-dotfiles/typescript-language-server"
            )
            _write_executable(
                final_root / "node_modules/.bin/typescript-language-server",
                "#!/bin/sh\necho old\n",
            )
            (final_root / "node_modules/typescript-language-server").mkdir(
                parents=True, exist_ok=True
            )
            (
                final_root
                / "node_modules/typescript-language-server/package.json"
            ).write_text(
                '{"name":"typescript-language-server","version":"5.0.0"}',
                encoding="utf-8",
            )

            result = self._run_script(TSLS_SH, root)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertTrue(
                (
                    final_root
                    / "node_modules/.bin/typescript-language-server"
                ).is_file(),
                "the existing typescript-language-server must survive an npm "
                "install failure",
            )

    def test_typescript_language_server_missing_node_returns_nonzero_and_keeps_existing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            final_root = (
                root / ".local/share/chezmoi-dotfiles/typescript-language-server"
            )
            _write_executable(
                final_root / "node_modules/.bin/typescript-language-server",
                "#!/bin/sh\necho old\n",
            )
            (final_root / "node_modules/typescript-language-server").mkdir(
                parents=True, exist_ok=True
            )
            (
                final_root
                / "node_modules/typescript-language-server/package.json"
            ).write_text(
                '{"name":"typescript-language-server","version":"5.0.0"}',
                encoding="utf-8",
            )

            result = self._run_script(TSLS_SH, root)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("Node", result.stderr)
            self.assertTrue(
                (
                    final_root
                    / "node_modules/.bin/typescript-language-server"
                ).is_file()
            )


class NoProfilePathResolutionTests(unittest.TestCase):
    """~/.profile を一切読まない no-profile なプロセス (GUI 起動や sandbox
    相当) でも、~/.local/bin の native symlink がまず解決され、
    ~/.local/share/mise/shims 配下に残った stale な旧 shim へ迷い込まない
    ことを、実際にコマンド名を解決・実行して確認する。"""

    @classmethod
    def setUpClass(cls) -> None:
        if BASH is None:
            raise unittest.SkipTest("bash is required for direct-install tests")
        cls.data = _load_data()

    def _stub_curl_must_not_run(self, root: pathlib.Path) -> dict[str, str]:
        stub_dir = root / "stub-bin"
        _write_executable(stub_dir / "curl", "#!/bin/sh\nexit 22\n")
        return {"PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}"}

    def _run_sh(
        self,
        sh_path: pathlib.Path,
        root: pathlib.Path,
        extra_env: dict[str, str],
    ) -> None:
        script = root / f"rendered-{sh_path.name}.sh"
        script.write_text(_render(sh_path, "linux", "amd64"), encoding="utf-8")
        env = dict(os.environ)
        env["HOME"] = _shell_path(root)
        env.update(extra_env)
        result = subprocess.run(
            [BASH, _shell_path(script)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, f"{sh_path.name}: {result.stderr}")

    def test_local_bin_entrypoints_resolve_before_stale_mise_shims_without_a_profile(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)

            # --- go: 完全な payload を final_root へ直接用意する。 ---
            go_version = self.data["go"]["version"]
            go_root = root / ".local/share/chezmoi-dotfiles/go"
            _write_executable(
                go_root / "bin/go",
                f"#!/bin/sh\necho \"go version go{go_version} linux/amd64\"\n",
            )
            _write_executable(go_root / "bin/gofmt", "#!/bin/sh\necho REAL-GOFMT\n")
            (go_root / "pkg/tool/linux_amd64").mkdir(parents=True)
            (go_root / "pkg/tool/linux_amd64/compile").write_text("stub\n")

            # --- node: node.sh 自身は `node --version` で版を確認し、
            # typescript-cli/typescript-lsp/typescript-language-server は
            # 同じ final_root の node を `-p "require(...).version" <pkg>`
            # で使って各自の package.json の版を読む。両方に応えられる
            # stub にしておく。 ---
            node_version = self.data["node"]["version"]
            node_root = root / ".local/share/chezmoi-dotfiles/node"
            _write_executable(
                node_root / "bin/node",
                "#!/bin/sh\n"
                "if [ \"$1\" = \"--version\" ]; then\n"
                f"  echo 'v{node_version}'\n"
                "  exit 0\n"
                "fi\n"
                "if [ \"$1\" = \"-p\" ]; then\n"
                "  pkg=\"$3\"\n"
                "  awk -F'\"' '{for (i = 1; i <= NF; i++) if ($i == "
                "\"version\") {print $(i + 2); exit}}' \"$pkg\"\n"
                "  exit 0\n"
                "fi\n"
                "exit 1\n",
            )
            _write_executable(node_root / "bin/npm", "#!/bin/sh\necho REAL-NPM\n")
            _write_executable(node_root / "bin/npx", "#!/bin/sh\necho REAL-NPX\n")
            (node_root / "lib/node_modules/npm/bin").mkdir(parents=True)
            (node_root / "lib/node_modules/npm/bin/npm-cli.js").write_text(
                "// stub\n"
            )
            (node_root / "lib/node_modules/npm/bin/npx-cli.js").write_text(
                "// stub\n"
            )
            (node_root / "lib/node_modules/npm/package.json").write_text(
                '{"name": "npm"}\n'
            )

            # --- dotnet ---
            dotnet_version = self.data["dotnet"]["version"]
            dotnet_root = root / ".local/share/chezmoi-dotfiles/dotnet"
            _write_executable(
                dotnet_root / "dotnet", f"#!/bin/sh\necho {dotnet_version}\n"
            )
            _write_executable(
                dotnet_root / "dnx", "#!/bin/sh\necho REAL-DNX\n"
            )
            sdk_dir = dotnet_root / "sdk" / dotnet_version
            (sdk_dir / "Sdks/Microsoft.NET.Sdk/Sdk").mkdir(parents=True)
            (sdk_dir / "dotnet.dll").write_text("stub dll\n")
            (sdk_dir / "Sdks/Microsoft.NET.Sdk/Sdk/Sdk.props").write_text(
                "<Project />\n"
            )

            # --- bun: 単一実行ファイルとして ~/.local/bin に直接置かれる。 ---
            bun_version = self.data["bun"]["version"]
            _write_executable(
                root / ".local/bin/bun", f"#!/bin/sh\necho '{bun_version}'\n"
            )

            # --- pnpm ---
            pnpm_version = self.data["pnpm"]["version"]
            pnpm_root = root / ".local/share/chezmoi-dotfiles/pnpm"
            _write_executable(
                pnpm_root / "pnpm", f"#!/bin/sh\necho '{pnpm_version}'\n"
            )
            (pnpm_root / "dist").mkdir(parents=True)
            (pnpm_root / "dist/pnpm.mjs").write_text("// stub\n")
            (pnpm_root / "dist/worker.js").write_text("// stub\n")

            # --- typescript-cli / typescript-lsp / typescript-language-server ---
            tscli_version = self.data["typescriptCli"]["version"]
            tscli_root = root / ".local/share/chezmoi-dotfiles/typescript-cli"
            _write_executable(
                tscli_root / "node_modules/.bin/tsc",
                f"#!/bin/sh\necho 'Version {tscli_version}'\n",
            )
            (tscli_root / "node_modules/typescript").mkdir(
                parents=True, exist_ok=True
            )
            (tscli_root / "node_modules/typescript/package.json").write_text(
                f'{{"name":"typescript","version":"{tscli_version}"}}',
                encoding="utf-8",
            )

            tslsp_version = self.data["typescriptLsp"]["version"]
            tslsp_root = root / ".local/share/chezmoi-dotfiles/typescript-lsp"
            _write_executable(
                tslsp_root / "node_modules/.bin/tsserver",
                "#!/bin/sh\necho REAL-TSSERVER\n",
            )
            (tslsp_root / "node_modules/typescript/lib").mkdir(
                parents=True, exist_ok=True
            )
            (tslsp_root / "node_modules/typescript/lib/tsserver.js").write_text(
                "// stub tsserver\n", encoding="utf-8"
            )
            (tslsp_root / "node_modules/typescript/package.json").write_text(
                f'{{"name":"typescript","version":"{tslsp_version}"}}',
                encoding="utf-8",
            )

            tsls_version = self.data["typescriptLanguageServer"]["version"]
            tsls_root = (
                root / ".local/share/chezmoi-dotfiles/typescript-language-server"
            )
            _write_executable(
                tsls_root / "node_modules/.bin/typescript-language-server",
                f"#!/bin/sh\necho '{tsls_version}'\n",
            )
            (tsls_root / "node_modules/typescript-language-server").mkdir(
                parents=True, exist_ok=True
            )
            (
                tsls_root
                / "node_modules/typescript-language-server/package.json"
            ).write_text(
                f'{{"name":"typescript-language-server","version":"{tsls_version}"}}',
                encoding="utf-8",
            )

            # --- 旧 mise shim (ADR-028 移行前の残骸) を、PATH には載せない
            # 「別の場所」にだけ物理的に残しておく。GUI/sandbox 由来の
            # no-profile プロセスは ~/.local/share/mise/shims を PATH に
            # 追加しないため、存在していても解決に影響しないはずである。 ---
            mise_shims = root / ".local/share/mise/shims"
            for name in (
                "go",
                "gofmt",
                "node",
                "npm",
                "npx",
                "dotnet",
                "dnx",
                "bun",
                "bunx",
                "pnpm",
                "tsc",
                "tsserver",
                "typescript-language-server",
            ):
                _write_executable(
                    mise_shims / name, f"#!/bin/sh\necho STALE-MISE-{name}\n"
                )

            # 各インストーラの「導入済みかつ版が一致」する早期 return 経路を
            # 走らせ、~/.local/bin の native symlink を (再)確認・発行させる。
            # 版が一致しているのでネットワークにも npm にも触れないはずで
            # あることを、curl / npm の両方を失敗する stub にして検証する。
            curl_env = self._stub_curl_must_not_run(root)
            self._run_sh(GO_SH, root, curl_env)
            self._run_sh(NODE_SH, root, curl_env)
            self._run_sh(DOTNET_SH, root, curl_env)
            self._run_sh(BUN_SH, root, curl_env)
            self._run_sh(PNPM_SH, root, curl_env)

            original_npm = (node_root / "bin/npm").read_text(encoding="utf-8")
            _write_executable(node_root / "bin/npm", "#!/bin/sh\nexit 1\n")
            self._run_sh(TS_CLI_SH, root, {})
            self._run_sh(TS_LSP_SH, root, {})
            self._run_sh(TSLS_SH, root, {})
            _write_executable(node_root / "bin/npm", original_npm)

            # --- no-profile なプロセスを模す: ~/.profile も mise の
            # activation も一切読まず、PATH は ~/.local/bin と OS 標準の
            # パスだけ。~/.local/share/mise/shims はここに含めない。 ---
            restricted_path = os.pathsep.join(
                [_shell_path(root / ".local/bin"), "/usr/bin", "/bin"]
            )
            restricted_env = {"PATH": restricted_path, "HOME": _shell_path(root)}

            checks = (
                ("go", (), f"go version go{go_version} linux/amd64"),
                ("gofmt", (), "REAL-GOFMT"),
                ("node", ("--version",), f"v{node_version}"),
                ("npm", (), "REAL-NPM"),
                ("npx", (), "REAL-NPX"),
                ("dotnet", (), dotnet_version),
                ("dnx", (), "REAL-DNX"),
                ("bun", (), bun_version),
                ("pnpm", (), pnpm_version),
                ("tsc", (), f"Version {tscli_version}"),
                ("tsserver", (), "REAL-TSSERVER"),
                ("typescript-language-server", (), tsls_version),
            )
            for name, args, expected_output in checks:
                which = subprocess.run(
                    [BASH, "-c", f"command -v {name}"],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=restricted_env,
                )
                self.assertEqual(
                    which.returncode, 0, f"{name} not resolvable: {which.stderr}"
                )
                resolved = pathlib.Path(which.stdout.strip())
                self.assertEqual(
                    resolved,
                    root / ".local/bin" / name,
                    f"{name} should resolve to the ~/.local/bin entrypoint "
                    f"first, got {resolved}",
                )

                run = subprocess.run(
                    [str(resolved), *args],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=restricted_env,
                )
                self.assertEqual(
                    run.returncode, 0, f"{name}: {run.stderr or run.stdout}"
                )
                self.assertIn(expected_output, run.stdout)
                self.assertNotIn(
                    "STALE-MISE",
                    run.stdout,
                    f"{name} must not execute the stale mise shim",
                )


if __name__ == "__main__":
    unittest.main()
