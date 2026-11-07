"""Guard the GitHub Copilot CLI installation contracts on Unix platforms.

Codespaces / Dev Container base images ship /usr/local/bin/copilot, which is
never refreshed by `copilot update`. Gating the official installer on
`command -v copilot` therefore pins an old CLI, so the gate must test the
repo-managed binary at ~/.local/bin/copilot instead.

macOS also uses the repo-managed binary because `copilot update` must not
modify a Homebrew formula while leaving Homebrew's package record stale.
"""
import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BOOTSTRAP_PATH = REPO_ROOT / "home/run_once_before_10-install-packages.sh.tmpl"
MACOS_COPILOT_PATH = (
    REPO_ROOT / "home/run_once_before_15-install-copilot-cli.sh.tmpl"
)
TOOLS_PATH = REPO_ROOT / "home/run_once_after_30-install-tools.sh.tmpl"
SHELL_SETUP_PATH = REPO_ROOT / "home/run_once_after_10-setup-shell.sh.tmpl"

COPILOT_RELEASES = {
    "amd64": (
        "copilot-linux-x64.tar.gz",
        "aff04181566f637010a88e68ea145ac1515ec596fae3890d06d81bb8c4be0c4e",
    ),
    "arm64": (
        "copilot-linux-arm64.tar.gz",
        "28c9c911af64521821ba908dc1866bf4bfd1705cd9b3320abc2353704de952a0",
    ),
}
MACOS_COPILOT_RELEASES = {
    "arm64": (
        "copilot-darwin-arm64.tar.gz",
        "85c58e1ba11a5869c9f5f59017571674ef6199e474c118caad3cb23ebe99448a",
    ),
}
MINIMUM_COPILOT_VERSION = "1.0.92-4"
AZD_RELEASES = {
    "amd64": "ac3640375d88372dd7f49bfda959e965da0038dc7f2909d44d761b28b4c43395",
    "arm64": "c4fe0824f71dcc163352cf00a7bb50eea5a9bad9f852364a0000c08056090267",
}
RUSTUP_RELEASES = {
    "Linux-x86_64": (
        "x86_64-unknown-linux-gnu",
        "b1c8cb14e30889e7e2999e6b69e62d9e9b9ffc0f4df8180564d306d9680e6c55",
    ),
    "Linux-aarch64|Linux-arm64": (
        "aarch64-unknown-linux-gnu",
        "9f608c142e0e38a78957d0661ba1dfaf0b6fb37184cfaa4b9a0aa57af6184282",
    ),
    "Darwin-arm64": (
        "aarch64-apple-darwin",
        "63752a1919a3a4793173ec70f8f212621a7ce38ba6a246095984482f4de20f9f",
    ),
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
        cls.macos_copilot = MACOS_COPILOT_PATH.read_text(encoding="utf-8")
        cls.tools = TOOLS_PATH.read_text(encoding="utf-8")
        cls.shell_setup = SHELL_SETUP_PATH.read_text(encoding="utf-8")

    def test_gate_uses_repo_managed_binary(self) -> None:
        self.assertIn('if [ ! -x "${HOME}/.local/bin/copilot" ]; then', self.bootstrap)

    def test_gate_does_not_regress_to_command_lookup(self) -> None:
        self.assertNotRegex(self.bootstrap, r"command -v copilot")

    def test_copilot_uses_pinned_verified_release(self) -> None:
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

    def test_macos_copilot_uses_pinned_verified_release(self) -> None:
        self.assertIn(
            '[ -f "${COPILOT_BIN}" ]',
            self.macos_copilot,
        )
        self.assertIn(
            '[ ! -L "${COPILOT_BIN}" ]',
            self.macos_copilot,
        )
        block = _case_block(self.macos_copilot, "COPILOT_VERSION")
        self.assertEqual(
            _parse_archives_and_checksums(block),
            MACOS_COPILOT_RELEASES,
        )
        self.assertIn(
            '"https://github.com/github/copilot-cli/releases/download/'
            'v${COPILOT_VERSION}/${copilot_archive}"',
            self.macos_copilot,
        )
        self.assertLess(
            self.macos_copilot.index(
                'actual_sha256="$(shasum -a 256 "${archive_path}"'
            ),
            self.macos_copilot.index('tar -xzf "${archive_path}"'),
        )
        self.assertIn(
            'mv -f "${staged_path}" "${COPILOT_BIN}"',
            self.macos_copilot,
        )
        self.assertRegex(
            self.macos_copilot,
            r"(?s)if ! curl .*?"
            r"failed to download GitHub Copilot CLI.*?exit 1",
        )
        self.assertIn(
            'echo "error: unsupported architecture for GitHub Copilot CLI: '
            '$(uname -m)" >&2',
            self.macos_copilot,
        )

    def test_copilot_release_versions_match_across_unix_platforms(self) -> None:
        linux_version = re.search(
            r'^\s*COPILOT_VERSION="([^"]+)"$',
            self.bootstrap,
            re.MULTILINE,
        )
        macos_version = re.search(
            r'^\s*COPILOT_VERSION="([^"]+)"$',
            self.macos_copilot,
            re.MULTILINE,
        )
        self.assertIsNotNone(linux_version)
        self.assertIsNotNone(macos_version)
        self.assertEqual(linux_version.group(1), macos_version.group(1))
        self.assertGreaterEqual(
            tuple(int(part) for part in re.findall(r"\d+", linux_version.group(1))),
            tuple(
                int(part)
                for part in re.findall(r"\d+", MINIMUM_COPILOT_VERSION)
            ),
        )

    def test_macos_copilot_removes_homebrew_formula_after_install(self) -> None:
        self.assertNotRegex(
            self.bootstrap,
            r"(?m)^\s*copilot-cli\s*\\?$",
        )
        install_index = self.macos_copilot.index(
            'mv -f "${staged_path}" "${COPILOT_BIN}"'
        )
        uninstall_index = self.macos_copilot.index(
            "brew uninstall --formula copilot-cli"
        )
        self.assertLess(install_index, uninstall_index)
        self.assertIn(
            "brew list --formula copilot-cli",
            self.macos_copilot,
        )
        self.assertIn(
            "if command -v brew >/dev/null 2>&1; then",
            self.macos_copilot,
        )
        verification_index = self.macos_copilot.index(
            'if ! is_user_local_copilot; then',
            install_index + 1,
        )
        self.assertLess(verification_index, uninstall_index)

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
        self.assertIn('AZD_VERSION="1.37.3"', self.bootstrap)
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
        self.assertIn('RUSTUP_VERSION="1.29.3"', self.bootstrap)
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

    def test_retired_desktop_apps_are_not_installed(self) -> None:
        managed_sources = self.bootstrap + self.tools
        self.assertNotRegex(managed_sources, r"(?i)draw\.io|drawio")
        self.assertNotRegex(managed_sources, r"(?i)libreoffice")

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
