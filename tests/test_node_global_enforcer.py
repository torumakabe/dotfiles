import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "home/private_dot_copilot/hooks/scripts/executable_node-global-enforcer.py"


def load_module():
    spec = importlib.util.spec_from_file_location("node_global_enforcer", SCRIPT_PATH)
    if spec is None:
        raise ImportError(f"Cannot load module: no spec for {SCRIPT_PATH}")
    if spec.loader is None:
        raise ImportError(f"Cannot load module: no loader for {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nge = load_module()


# ── npm ───────────────────────────────────────────────────────────────────


class TestNpmGlobalBlocked(unittest.TestCase):
    """npm install -g / --global must be denied."""

    def test_npm_install_g(self) -> None:
        self.assertIsNotNone(nge.check_command("npm install -g typescript"))

    def test_npm_i_g(self) -> None:
        self.assertIsNotNone(nge.check_command("npm i -g typescript"))

    def test_npm_install_global(self) -> None:
        self.assertIsNotNone(nge.check_command("npm install --global typescript"))

    def test_npm_add_g(self) -> None:
        self.assertIsNotNone(nge.check_command("npm add -g typescript"))

    def test_npm_g_before_subcommand(self) -> None:
        """npm -g install foo (flag before subcommand)."""
        self.assertIsNotNone(nge.check_command("npm -g install typescript"))

    def test_npm_global_multiple_packages(self) -> None:
        self.assertIsNotNone(nge.check_command("npm install -g typescript eslint"))

    def test_npm_global_with_env_prefix(self) -> None:
        self.assertIsNotNone(nge.check_command("NODE_ENV=production npm install -g foo"))

    def test_npm_location_global_equals(self) -> None:
        self.assertIsNotNone(nge.check_command("npm install --location=global typescript"))

    def test_npm_location_global_space(self) -> None:
        self.assertIsNotNone(nge.check_command("npm install --location global typescript"))

    def test_npm_link_g(self) -> None:
        self.assertIsNotNone(nge.check_command("npm link -g"))

    def test_npm_link_bare(self) -> None:
        """npm link without -g still modifies global node_modules."""
        self.assertIsNotNone(nge.check_command("npm link"))

    def test_npm_link_package(self) -> None:
        """npm link <pkg> interacts with global node_modules."""
        self.assertIsNotNone(nge.check_command("npm link express"))

    def test_npm_ln(self) -> None:
        """npm ln is an alias for npm link."""
        self.assertIsNotNone(nge.check_command("npm ln"))

    def test_npm_ln_package(self) -> None:
        self.assertIsNotNone(nge.check_command("npm ln express"))

    def test_sudo_npm_install_g(self) -> None:
        self.assertIsNotNone(nge.check_command("sudo npm install -g typescript"))

    def test_sudo_E_npm_install_g(self) -> None:
        self.assertIsNotNone(nge.check_command("sudo -E npm install -g typescript"))

    def test_env_npm_install_g(self) -> None:
        self.assertIsNotNone(nge.check_command("env npm install -g typescript"))

    def test_absolute_path_npm(self) -> None:
        self.assertIsNotNone(nge.check_command("/usr/bin/npm install -g typescript"))

    def test_absolute_path_local_npm(self) -> None:
        self.assertIsNotNone(nge.check_command("/usr/local/bin/npm install -g foo"))

    def test_absolute_path_env_npm(self) -> None:
        """/usr/bin/env npm install -g must not bypass prefix detection."""
        self.assertIsNotNone(nge.check_command("/usr/bin/env npm install -g foo"))

    def test_absolute_path_sudo_npm(self) -> None:
        """/usr/bin/sudo npm install -g must not bypass prefix detection."""
        self.assertIsNotNone(nge.check_command("/usr/bin/sudo npm install -g foo"))

    def test_sudo_u_npm_install_g(self) -> None:
        """sudo -u root npm install -g must not bypass via flag argument."""
        self.assertIsNotNone(nge.check_command("sudo -u root npm install -g typescript"))

    def test_sudo_u_user_npm_install_g(self) -> None:
        self.assertIsNotNone(nge.check_command("sudo -u nobody npm install -g foo"))

    def test_env_u_npm_install_g(self) -> None:
        """env -u VAR npm install -g must not bypass via flag argument."""
        self.assertIsNotNone(nge.check_command("env -u NODE_ENV npm install -g foo"))

    def test_corepack_yarn_global_add(self) -> None:
        """corepack yarn global add must be blocked."""
        self.assertIsNotNone(nge.check_command("corepack yarn global add typescript"))

    def test_corepack_pnpm_add_g(self) -> None:
        """corepack pnpm add -g must be blocked."""
        self.assertIsNotNone(nge.check_command("corepack pnpm add -g typescript"))

    def test_command_npm_install_g(self) -> None:
        """command npm install -g must not bypass via command builtin."""
        self.assertIsNotNone(nge.check_command("command npm install -g typescript"))

    def test_yarn_silent_global_add(self) -> None:
        """yarn --silent global add must be blocked despite leading flags."""
        self.assertIsNotNone(nge.check_command("yarn --silent global add typescript"))

    def test_yarn_cwd_global_add(self) -> None:
        """yarn --cwd /repo global add must be blocked."""
        self.assertIsNotNone(nge.check_command("yarn --cwd /repo global add typescript"))


class TestNpmLocalAllowed(unittest.TestCase):
    """Local npm operations must be allowed."""

    def test_npm_install_local(self) -> None:
        self.assertIsNone(nge.check_command("npm install typescript"))

    def test_npm_i_local(self) -> None:
        self.assertIsNone(nge.check_command("npm i"))

    def test_npm_install_save_dev(self) -> None:
        self.assertIsNone(nge.check_command("npm install -D typescript"))

    def test_npm_ci(self) -> None:
        self.assertIsNone(nge.check_command("npm ci"))

    def test_npm_run(self) -> None:
        self.assertIsNone(nge.check_command("npm run build"))

    def test_npm_test(self) -> None:
        self.assertIsNone(nge.check_command("npm test"))

    def test_npx_allowed(self) -> None:
        self.assertIsNone(nge.check_command("npx create-react-app my-app"))

    def test_npm_uninstall_g_allowed(self) -> None:
        """Cleaning up global packages is allowed."""
        self.assertIsNone(nge.check_command("npm uninstall -g typescript"))

    def test_npm_install_double_dash_g(self) -> None:
        """npm install -- -g treats -g as a package name, not a flag."""
        self.assertIsNone(nge.check_command("npm install -- -g typescript"))

    def test_npm_install_link_package(self) -> None:
        """npm install link (package named 'link') must be allowed."""
        self.assertIsNone(nge.check_command("npm install link"))

    def test_npm_install_ln_package(self) -> None:
        """npm install ln (package named 'ln') must be allowed."""
        self.assertIsNone(nge.check_command("npm install ln"))

    def test_pipe_no_false_positive(self) -> None:
        """Pipe right-side -g flag must not trigger false positive."""
        self.assertIsNone(nge.check_command("npm install foo | tee -g log.txt"))


# ── yarn ──────────────────────────────────────────────────────────────────


class TestYarnGlobalBlocked(unittest.TestCase):

    def test_yarn_global_add(self) -> None:
        self.assertIsNotNone(nge.check_command("yarn global add typescript"))

    def test_sudo_yarn_global_add(self) -> None:
        self.assertIsNotNone(nge.check_command("sudo yarn global add typescript"))


class TestYarnLocalAllowed(unittest.TestCase):

    def test_yarn_add_local(self) -> None:
        self.assertIsNone(nge.check_command("yarn add typescript"))

    def test_yarn_install(self) -> None:
        self.assertIsNone(nge.check_command("yarn install"))


# ── pnpm ──────────────────────────────────────────────────────────────────


class TestPnpmGlobalBlocked(unittest.TestCase):

    def test_pnpm_add_g(self) -> None:
        self.assertIsNotNone(nge.check_command("pnpm add -g typescript"))

    def test_pnpm_install_global(self) -> None:
        self.assertIsNotNone(nge.check_command("pnpm install --global typescript"))

    def test_pnpm_link_global(self) -> None:
        self.assertIsNotNone(nge.check_command("pnpm link --global"))


class TestPnpmLocalAllowed(unittest.TestCase):

    def test_pnpm_add_local(self) -> None:
        self.assertIsNone(nge.check_command("pnpm add typescript"))

    def test_pnpm_dlx_allowed(self) -> None:
        self.assertIsNone(nge.check_command("pnpm dlx create-react-app my-app"))


# ── bun ───────────────────────────────────────────────────────────────────


class TestBunGlobalBlocked(unittest.TestCase):

    def test_bun_add_g(self) -> None:
        self.assertIsNotNone(nge.check_command("bun add -g typescript"))

    def test_bun_install_global(self) -> None:
        self.assertIsNotNone(nge.check_command("bun install --global typescript"))


class TestBunLocalAllowed(unittest.TestCase):

    def test_bun_add_local(self) -> None:
        self.assertIsNone(nge.check_command("bun add typescript"))

    def test_bunx_allowed(self) -> None:
        self.assertIsNone(nge.check_command("bunx create-react-app my-app"))


# ── Shell chains & pipes ─────────────────────────────────────────────────


class TestShellChains(unittest.TestCase):

    def test_chained_global_install(self) -> None:
        self.assertIsNotNone(nge.check_command("echo ok && npm install -g foo"))

    def test_chained_local_only(self) -> None:
        self.assertIsNone(nge.check_command("npm install && npm test"))

    def test_piped_global_install(self) -> None:
        self.assertIsNotNone(nge.check_command("echo foo | npm install -g bar"))

    def test_semicolon_chained(self) -> None:
        self.assertIsNotNone(nge.check_command("cd /tmp; npm i -g eslint"))


# ── Non-shell tools ──────────────────────────────────────────────────────


class TestNonShellToolsAllowed(unittest.TestCase):

    def test_empty_command(self) -> None:
        self.assertIsNone(nge.check_command(""))

    def test_unrelated_command(self) -> None:
        self.assertIsNone(nge.check_command("git status"))

    def test_node_direct(self) -> None:
        self.assertIsNone(nge.check_command("node script.js"))


# ── Integration tests (stdin → stdout) ───────────────────────────────────


class TestMainIntegration(unittest.TestCase):
    """Exercise the full stdin → stdout JSON flow."""

    def _run_hook(self, input_data: dict) -> dict:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        return json.loads(result.stdout)

    def test_deny_global_install(self) -> None:
        out = self._run_hook({
            "toolName": "bash",
            "toolArgs": {"command": "npm install -g typescript"},
        })
        self.assertEqual(out["permissionDecision"], "deny")

    def test_allow_local_install(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            input=json.dumps({
                "toolName": "bash",
                "toolArgs": {"command": "npm install typescript"},
            }),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_allow_non_bash_tool(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            input=json.dumps({
                "toolName": "edit",
                "toolArgs": {"path": "/tmp/foo.txt"},
            }),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_invalid_json_denies(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            input="not valid json",
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        self.assertEqual(out["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
