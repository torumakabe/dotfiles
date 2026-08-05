"""Guard the Copilot CLI install predicate in the Linux package bootstrap.

Codespaces / Dev Container base images ship /usr/local/bin/copilot, which is
never refreshed by `copilot update`. Gating the official installer on
`command -v copilot` therefore pins an old CLI, so the gate must test the
repo-managed binary at ~/.local/bin/copilot instead.
"""
import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BOOTSTRAP_PATH = REPO_ROOT / "home/run_once_before_10-install-packages.sh.tmpl"
INSTALL_COMMAND = "curl -fsSL https://gh.io/copilot-install | bash"


class CopilotCliInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bootstrap = BOOTSTRAP_PATH.read_text(encoding="utf-8")

    def test_gate_uses_repo_managed_binary(self) -> None:
        self.assertIn('if [ ! -x "${HOME}/.local/bin/copilot" ]; then', self.bootstrap)

    def test_gate_does_not_regress_to_command_lookup(self) -> None:
        self.assertNotRegex(self.bootstrap, r"command -v copilot")

    def test_installer_uses_official_command(self) -> None:
        self.assertIn(INSTALL_COMMAND, self.bootstrap)
        self.assertNotIn("unset GITHUB_TOKEN GH_TOKEN", self.bootstrap)

    def test_install_failure_does_not_abort_apply(self) -> None:
        # The script runs under `set -euo pipefail`; an unguarded install would
        # stop every later chezmoi script.
        self.assertIn(f"if ! {INSTALL_COMMAND}; then", self.bootstrap)
        self.assertIn("Warning: Copilot CLI installation failed.", self.bootstrap)


if __name__ == "__main__":
    unittest.main()
