"""Guard the Copilot CLI install predicate in the Linux package bootstrap.

Codespaces / Dev Container base images ship /usr/local/bin/copilot, which is
never refreshed by `copilot update`. Gating the official installer on
`command -v copilot` therefore pins an old CLI, so the gate must test the
repo-managed binary at ~/.local/bin/copilot instead.
"""
import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BOOTSTRAP_PATH = REPO_ROOT / "home/run_once_before_10-install-packages.sh.tmpl"
TOOLS_PATH = REPO_ROOT / "home/run_once_after_30-install-tools.sh.tmpl"
SHELL_SETUP_PATH = REPO_ROOT / "home/run_once_after_10-setup-shell.sh.tmpl"

COPILOT_RELEASES = {
    "amd64": (
        "copilot-linux-x64.tar.gz",
        "039933c9247686131c4406abb1d439bdbf68103edc1ff585bd70d5b0dc940f72",
    ),
    "arm64": (
        "copilot-linux-arm64.tar.gz",
        "3ed85e711955e13be523bf492bc6c93b40b69925bcb7f817c9d08abf4839cf89",
    ),
}
AZD_RELEASES = {
    "amd64": "414bc5a111ade678f2bf81f5396019b8c42e6151154a7e332307e7ce1146180e",
    "arm64": "009dae211c4a8f9001f7e7dd3aca88e89caba9d45a7e7c80506c9d8372c95514",
}
RUSTUP_RELEASES = {
    "Linux-x86_64": (
        "x86_64-unknown-linux-gnu",
        "4acc9acc76d5079515b46346a485974457b5a79893cfb01112423c89aeb5aa10",
    ),
    "Linux-aarch64|Linux-arm64": (
        "aarch64-unknown-linux-gnu",
        "9732d6c5e2a098d3521fca8145d826ae0aaa067ef2385ead08e6feac88fa5792",
    ),
    "Darwin-x86_64": (
        "x86_64-apple-darwin",
        "33cf85df9142bc6d29cbc62fa5ca1d4c29622cddb55213a4c1a43c457fb9b2d7",
    ),
    "Darwin-arm64": (
        "aarch64-apple-darwin",
        "aeb4105778ca1bd3c6b0e75768f581c656633cd51368fa61289b6a71696ac7e1",
    ),
}
DRAWIO_RELEASES = {
    "amd64": "f4c49ed84422ea4afd95818f53c54bc666e57b33bd036d468c7096619b47ffd9",
    "arm64": "62a9ea636accada76076bd5a20f61b707e0e8093d3fd28c6583518663ca795d6",
}


def _case_block(source: str, version_variable: str) -> str:
    start = source.index(f'{version_variable}="')
    end = source.index("esac", start)
    return source[start:end]


def _parse_archives_and_checksums(block: str) -> dict[str, tuple[str, str]]:
    return {
        arch: (asset, checksum)
        for arch, asset, checksum in re.findall(
            r'^\s*([A-Za-z0-9_|-]+)\)\s*'
            r'\n\s*\w+_(?:archive|target)="([^"]+)"'
            r'\n\s*expected_sha256="([0-9a-f]{64})"',
            block,
            re.MULTILINE,
        )
    }


def _parse_checksums(block: str) -> dict[str, str]:
    return {
        arch: checksum
        for arch, checksum in re.findall(
            r'^\s*([A-Za-z0-9_|-]+)\)\s*'
            r'expected_sha256="([0-9a-f]{64})"',
            block,
            re.MULTILINE,
        )
    }


class CopilotCliInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bootstrap = BOOTSTRAP_PATH.read_text(encoding="utf-8")
        cls.tools = TOOLS_PATH.read_text(encoding="utf-8")
        cls.shell_setup = SHELL_SETUP_PATH.read_text(encoding="utf-8")

    def test_gate_uses_repo_managed_binary(self) -> None:
        self.assertIn('if [ ! -x "${HOME}/.local/bin/copilot" ]; then', self.bootstrap)

    def test_gate_does_not_regress_to_command_lookup(self) -> None:
        self.assertNotRegex(self.bootstrap, r"command -v copilot")

    def test_copilot_uses_pinned_verified_release(self) -> None:
        self.assertIn('COPILOT_VERSION="1.0.80"', self.bootstrap)
        block = _case_block(self.bootstrap, "COPILOT_VERSION")
        self.assertEqual(
            _parse_archives_and_checksums(block),
            COPILOT_RELEASES,
        )
        self.assertNotIn("gh.io/copilot-install", self.bootstrap)
        self.assertIn(
            '"https://github.com/github/copilot-cli/releases/download/'
            'v${COPILOT_VERSION}/${copilot_archive}"',
            self.bootstrap,
        )
        self.assertLess(
            self.bootstrap.index('actual_sha256="$(sha256_file "${archive_path}")"'),
            self.bootstrap.index('tar -xzf "${archive_path}"'),
        )
        install_block = self.bootstrap[
            self.bootstrap.index("if ! download_file", self.bootstrap.index("COPILOT_VERSION")):
            self.bootstrap.index("# GitHub CLI")
        ]
        self.assertLess(
            install_block.index("Warning: failed to download GitHub Copilot CLI"),
            install_block.index("checksum verification failed"),
        )
        self.assertIn("exit 0", install_block)
        self.assertIn("exit 1", install_block)

    def test_azure_cli_uses_verified_microsoft_repository(self) -> None:
        self.assertNotIn("InstallAzureCLIDeb", self.bootstrap)
        self.assertIn(
            'expected_fingerprint="BC528686B50D79E339D3721CEB3E94ADBE1229CF"',
            self.bootstrap,
        )
        self.assertIn("signed-by=/etc/apt/keyrings/microsoft.gpg", self.bootstrap)
        self.assertIn(
            'GNUPGHOME="${microsoft_key_home}" gpg --batch --export '
            '"${expected_fingerprint}"',
            self.bootstrap,
        )
        self.assertNotIn("gpg --batch --yes --dearmor", self.bootstrap)
        self.assertIn(
            '[ "${exported_fingerprints}" != "${expected_fingerprint}" ]',
            self.bootstrap,
        )
        self.assertLess(
            self.bootstrap.index("fingerprint verification failed"),
            self.bootstrap.index("sudo apt-get install -y -qq azure-cli"),
        )

    def test_azure_cli_codename_fallbacks_and_supported_suites(self) -> None:
        self.assertIn(
            'repository_suite="$(azure_cli_suite "${VERSION_CODENAME}")" || true',
            self.bootstrap,
        )
        self.assertIn(
            'repository_suite="$(azure_cli_suite "${UBUNTU_CODENAME}")" || true',
            self.bootstrap,
        )
        self.assertLess(
            self.bootstrap.index('azure_cli_suite "${VERSION_CODENAME}"'),
            self.bootstrap.index('azure_cli_suite "${UBUNTU_CODENAME}"'),
        )
        suite_function = self.bootstrap[
            self.bootstrap.index("azure_cli_suite() {"):
            self.bootstrap.index("\n}", self.bootstrap.index("azure_cli_suite() {")) + 2
        ]
        self.assertIn("bullseye|bookworm|jammy|noble)", suite_function)
        self.assertIn("return 1", suite_function)
        self.assertIn(
            "unsupported distribution codename for the Azure CLI repository",
            self.bootstrap,
        )
        self.assertRegex(
            self.bootstrap,
            r'(?s)if \[ -z "\$\{repository_suite\}" \]; then.*?'
            r'unsupported distribution codename.*?exit 0',
        )

    def test_microsoft_key_download_failure_warns_but_mismatch_aborts(self) -> None:
        azure_block = self.bootstrap[
            self.bootstrap.index("# Azure CLI"):
            self.bootstrap.index("# Azure Developer CLI")
        ]
        self.assertRegex(
            azure_block,
            r'(?s)if ! download_file "https://packages\.microsoft\.com/keys/'
            r'microsoft\.asc".*?Warning: failed to download.*?exit 0',
        )
        self.assertRegex(
            azure_block,
            r'(?s)fingerprint verification failed.*?exit 1',
        )

    def test_azd_uses_pinned_verified_release(self) -> None:
        self.assertIn('AZD_VERSION="1.31.1"', self.bootstrap)
        self.assertNotIn("aka.ms/install-azd.sh", self.bootstrap)
        azd_block = _case_block(self.bootstrap, "AZD_VERSION")
        self.assertEqual(_parse_checksums(azd_block), AZD_RELEASES)
        self.assertIn(
            '"https://github.com/Azure/azure-dev/releases/download/'
            'azure-dev-cli_${AZD_VERSION}/'
            'azd_${AZD_VERSION}_$(dpkg --print-architecture).deb"',
            self.bootstrap,
        )
        self.assertLess(
            self.bootstrap.index('actual_sha256="$(sha256_file "${azd_deb}")"'),
            self.bootstrap.index('sudo apt-get install -y -qq "${azd_deb}"'),
        )

    def test_rustup_uses_pinned_verified_binary(self) -> None:
        self.assertIn('RUSTUP_VERSION="1.29.0"', self.bootstrap)
        self.assertNotIn("sh.rustup.rs", self.bootstrap)
        rustup_block = _case_block(self.bootstrap, "RUSTUP_VERSION")
        self.assertEqual(
            _parse_archives_and_checksums(rustup_block),
            RUSTUP_RELEASES,
        )
        self.assertIn(
            '"https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/'
            '${rustup_target}/rustup-init"',
            self.bootstrap,
        )
        self.assertLess(
            self.bootstrap.index('actual_sha256="$(sha256_file "${rustup_init}")"'),
            self.bootstrap.index('"${rustup_init}" -y --no-modify-path'),
        )

    def test_drawio_uses_pinned_verified_release(self) -> None:
        self.assertIn('DRAWIO_VERSION="31.1.8"', self.tools)
        self.assertNotIn("/releases/latest", self.tools)
        block = _case_block(self.tools, "DRAWIO_VERSION")
        self.assertEqual(_parse_checksums(block), DRAWIO_RELEASES)
        self.assertIn(
            '"https://github.com/jgraph/drawio-desktop/releases/download/'
            'v${DRAWIO_VERSION}/${deb_name}"',
            self.tools,
        )
        self.assertLess(
            self.tools.index('actual_sha256="$(sha256_file "${deb_path}")"'),
            self.tools.index('sudo dpkg -i "${deb_path}"'),
        )
        self.assertNotIn("installation failed, skipping", self.tools)

    def test_download_failures_warn_and_checksums_fail_closed(self) -> None:
        cases = (
            (self.bootstrap, "GitHub Copilot CLI", "${copilot_archive}"),
            (self.bootstrap, "Azure Developer CLI", "Azure Developer CLI"),
            (self.bootstrap, "rustup-init", "rustup-init"),
            (self.tools, "draw.io", "${deb_name}"),
        )
        for source, name, payload in cases:
            with self.subTest(name=name):
                self.assertRegex(
                    source,
                    rf"(?s)Warning: failed to download {re.escape(name)}.*?exit 0",
                )
                self.assertRegex(
                    source,
                    rf'echo "error: checksum verification failed for '
                    rf'{re.escape(payload)}" >&2[ \t]*\n[ \t]*exit 1',
                )

    def test_shell_git_dependencies_use_verified_commits(self) -> None:
        self.assertIsNotNone(
            re.search(
                r'^ZSH_COMPLETIONS_TAG="[^"\r\n]+"$',
                self.shell_setup,
                re.MULTILINE,
            )
        )
        self.assertNotIn("git clone --branch", self.shell_setup)
        for dependency in ("OH_MY_ZSH", "ZSH_COMPLETIONS"):
            with self.subTest(dependency=dependency):
                self.assertIsNotNone(
                    re.search(
                        rf'^{dependency}_COMMIT="[0-9a-f]{{40}}"$',
                        self.shell_setup,
                        re.MULTILINE,
                    )
                )
                self.assertIn(
                    f'fetch --depth=1 origin "${{{dependency}_COMMIT}}"',
                    self.shell_setup,
                )
                self.assertIn(
                    f'rev-parse HEAD)" != "${{{dependency}_COMMIT}}"',
                    self.shell_setup,
                )


if __name__ == "__main__":
    unittest.main()
