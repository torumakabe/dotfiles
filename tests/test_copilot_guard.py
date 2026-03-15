import importlib.util
import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "home/private_dot_copilot/hooks/scripts/executable_copilot-guard.py"


def load_module():
    spec = importlib.util.spec_from_file_location("copilot_guard", SCRIPT_PATH)
    if spec is None:
        raise ImportError(f"Cannot load copilot_guard: no module spec found for {SCRIPT_PATH}")
    if spec.loader is None:
        raise ImportError(f"Cannot load copilot_guard: no loader available for spec from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


copilot_guard = load_module()


class CopilotGuardPathMatchingTests(unittest.TestCase):
    def test_does_not_match_by_substring(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "/tmp/accessTokens.json.backup",
            ["**/accessTokens.json"],
        )
        self.assertIsNone(hit)

    def test_matches_windows_path_after_normalization(self) -> None:
        hit = copilot_guard.check_blocked_path(
            r"C:\Users\me\.azure\accessTokens.json",
            ["**/accessTokens.json"],
        )
        self.assertEqual(hit, "**/accessTokens.json")

    def test_matches_nested_unix_path(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "/home/me/project/.azure/dev/.env",
            ["**/.azure/**/.env"],
        )
        self.assertEqual(hit, "**/.azure/**/.env")

    def test_matches_file_uri(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "file:///C:/Users/me/.azure/accessTokens.json",
            ["**/accessTokens.json"],
        )
        self.assertEqual(hit, "**/accessTokens.json")

    def test_matches_file_uri_with_netloc(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "file://server/share/.azure/accessTokens.json",
            ["**/accessTokens.json"],
        )
        self.assertEqual(hit, "**/accessTokens.json")


class CopilotGuardCommandMatchingTests(unittest.TestCase):
    def test_command_ignores_non_path_substrings(self) -> None:
        hit = copilot_guard.check_blocked_command(
            'echo os.environ["PATH"]',
            ["**/.env"],
        )
        self.assertIsNone(hit)

    def test_command_matches_windows_assignment_argument(self) -> None:
        hit = copilot_guard.check_blocked_command(
            'type --file="C:\\Users\\me\\.azure\\accessTokens.json"',
            ["**/accessTokens.json"],
        )
        self.assertEqual(hit, "**/accessTokens.json")

    def test_command_matches_quoted_windows_path_with_spaces(self) -> None:
        hit = copilot_guard.check_blocked_command(
            'type --file="C:\\Users\\John Doe\\.azure\\accessTokens.json"',
            ["**/accessTokens.json"],
        )
        self.assertEqual(hit, "**/accessTokens.json")


class CopilotGuardEnvBlockingTests(unittest.TestCase):
    """Tests for environment variable access blocking."""

    # --- Dump commands ---

    def test_blocks_printenv(self) -> None:
        result = copilot_guard.check_env_access("printenv")
        self.assertIsNotNone(result)
        self.assertIn("printenv", result)

    def test_blocks_printenv_with_pipe(self) -> None:
        result = copilot_guard.check_env_access("printenv | grep SECRET")
        self.assertIsNotNone(result)

    def test_blocks_bare_env(self) -> None:
        result = copilot_guard.check_env_access("env")
        self.assertIsNotNone(result)

    def test_allows_env_i(self) -> None:
        result = copilot_guard.check_env_access("env -i PATH=/usr/bin bash")
        self.assertIsNone(result)

    def test_allows_env_u(self) -> None:
        result = copilot_guard.check_env_access("env -u SECRET command")
        self.assertIsNone(result)

    def test_allows_env_with_assignment(self) -> None:
        result = copilot_guard.check_env_access("env FOO=bar command")
        self.assertIsNone(result)

    def test_allows_env_double_dash(self) -> None:
        result = copilot_guard.check_env_access("env -- command")
        self.assertIsNone(result)

    def test_blocks_bare_set(self) -> None:
        result = copilot_guard.check_env_access("set")
        self.assertIsNotNone(result)

    def test_allows_set_with_options(self) -> None:
        result = copilot_guard.check_env_access("set -e")
        self.assertIsNone(result)

    def test_allows_set_euo_pipefail(self) -> None:
        result = copilot_guard.check_env_access("set -euo pipefail")
        self.assertIsNone(result)

    def test_blocks_declare_p(self) -> None:
        result = copilot_guard.check_env_access("declare -p")
        self.assertIsNotNone(result)

    def test_blocks_export_p(self) -> None:
        result = copilot_guard.check_env_access("export -p")
        self.assertIsNotNone(result)

    def test_blocks_compgen_v(self) -> None:
        result = copilot_guard.check_env_access("compgen -v")
        self.assertIsNotNone(result)

    def test_blocks_compgen_e(self) -> None:
        result = copilot_guard.check_env_access("compgen -e")
        self.assertIsNotNone(result)

    # --- Sensitive variable expansion ---

    def test_blocks_github_token(self) -> None:
        result = copilot_guard.check_env_access("echo $GITHUB_TOKEN")
        self.assertIsNotNone(result)

    def test_blocks_secret_key_braces(self) -> None:
        result = copilot_guard.check_env_access("echo ${SECRET_KEY}")
        self.assertIsNotNone(result)

    def test_blocks_azure_client_secret(self) -> None:
        result = copilot_guard.check_env_access('echo "$AZURE_CLIENT_SECRET"')
        self.assertIsNotNone(result)

    def test_blocks_api_key(self) -> None:
        result = copilot_guard.check_env_access("curl -H 'Authorization: $API_KEY'")
        self.assertIsNotNone(result)

    def test_blocks_db_password(self) -> None:
        result = copilot_guard.check_env_access("mysql -p$DB_PASSWORD")
        self.assertIsNotNone(result)

    def test_blocks_connection_string(self) -> None:
        result = copilot_guard.check_env_access("echo $DATABASE_CONNECTION_STRING")
        self.assertIsNotNone(result)

    def test_blocks_auth_token(self) -> None:
        result = copilot_guard.check_env_access("echo $AUTH_TOKEN")
        self.assertIsNotNone(result)

    # --- Safe variables ---

    def test_allows_path(self) -> None:
        result = copilot_guard.check_env_access("echo $PATH")
        self.assertIsNone(result)

    def test_allows_home(self) -> None:
        result = copilot_guard.check_env_access("echo $HOME")
        self.assertIsNone(result)

    def test_allows_shell(self) -> None:
        result = copilot_guard.check_env_access("echo $SHELL")
        self.assertIsNone(result)

    def test_allows_user(self) -> None:
        result = copilot_guard.check_env_access("echo $USER")
        self.assertIsNone(result)

    def test_allows_node_env(self) -> None:
        result = copilot_guard.check_env_access("echo $NODE_ENV")
        self.assertIsNone(result)

    def test_allows_editor(self) -> None:
        result = copilot_guard.check_env_access("echo $EDITOR")
        self.assertIsNone(result)

    def test_allows_ssh_auth_sock(self) -> None:
        result = copilot_guard.check_env_access("echo $SSH_AUTH_SOCK")
        self.assertIsNone(result)

    def test_allows_xdg_config_home(self) -> None:
        result = copilot_guard.check_env_access("echo $XDG_CONFIG_HOME")
        self.assertIsNone(result)

    def test_allows_tmpdir(self) -> None:
        result = copilot_guard.check_env_access("echo $TMPDIR")
        self.assertIsNone(result)

    def test_allows_pwd(self) -> None:
        result = copilot_guard.check_env_access("echo $PWD")
        self.assertIsNone(result)

    # --- Language runtime env dumps ---

    def test_blocks_python_os_environ(self) -> None:
        result = copilot_guard.check_env_access(
            'uv run python -c "import os; print(os.environ)"'
        )
        self.assertIsNotNone(result)

    def test_blocks_node_process_env(self) -> None:
        result = copilot_guard.check_env_access(
            'node -e "console.log(process.env)"'
        )
        self.assertIsNotNone(result)

    def test_blocks_perl_env(self) -> None:
        result = copilot_guard.check_env_access(
            'perl -e \'foreach (keys %ENV) { print }\''
        )
        self.assertIsNotNone(result)

    def test_blocks_ruby_env_to_h(self) -> None:
        result = copilot_guard.check_env_access(
            'ruby -e "puts ENV.to_h"'
        )
        self.assertIsNotNone(result)

    def test_blocks_powershell_get_childitem_env(self) -> None:
        result = copilot_guard.check_env_access(
            "Get-ChildItem Env:"
        )
        self.assertIsNotNone(result)

    # --- Compound commands ---

    def test_blocks_env_in_pipe_chain(self) -> None:
        result = copilot_guard.check_env_access("ls && printenv | grep SECRET")
        self.assertIsNotNone(result)

    def test_blocks_sensitive_var_in_chained_command(self) -> None:
        result = copilot_guard.check_env_access(
            "cd /tmp && echo $GITHUB_TOKEN"
        )
        self.assertIsNotNone(result)

    # --- Empty / safe commands ---

    def test_allows_empty_command(self) -> None:
        result = copilot_guard.check_env_access("")
        self.assertIsNone(result)

    def test_allows_normal_command(self) -> None:
        result = copilot_guard.check_env_access("ls -la /tmp")
        self.assertIsNone(result)

    def test_allows_git_commands(self) -> None:
        result = copilot_guard.check_env_access("git --no-pager status")
        self.assertIsNone(result)


class CopilotGuardNewBlockedPatternsTests(unittest.TestCase):
    """Tests for newly added blocked-files.txt patterns (Copilot hooks, SSH, .github/hooks)."""

    # --- Copilot CLI 設定・Hook (改変防止) ---

    def test_blocks_copilot_hooks_direct_child(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "/home/user/.copilot/hooks/hooks.json",
            ["**/.copilot/hooks/**"],
        )
        self.assertEqual(hit, "**/.copilot/hooks/**")

    def test_blocks_copilot_hooks_config_file(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "/home/user/.copilot/hooks/blocked-files.txt",
            ["**/.copilot/hooks/**"],
        )
        self.assertEqual(hit, "**/.copilot/hooks/**")

    def test_blocks_copilot_hooks_nested_script(self) -> None:
        """Critical: scripts/ subdirectory must be protected to prevent 2-step attacks."""
        hit = copilot_guard.check_blocked_path(
            "/home/user/.copilot/hooks/scripts/copilot-guard.py",
            ["**/.copilot/hooks/**"],
        )
        self.assertEqual(hit, "**/.copilot/hooks/**")

    def test_blocks_copilot_hooks_nested_audit_log(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "/home/user/.copilot/hooks/scripts/audit-log.py",
            ["**/.copilot/hooks/**"],
        )
        self.assertEqual(hit, "**/.copilot/hooks/**")

    def test_blocks_copilot_mcp_config(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "/home/user/.copilot/mcp-config.json",
            ["**/.copilot/mcp-config.json"],
        )
        self.assertEqual(hit, "**/.copilot/mcp-config.json")

    def test_blocks_copilot_config(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "/home/user/.copilot/config.json",
            ["**/.copilot/config.json"],
        )
        self.assertEqual(hit, "**/.copilot/config.json")

    def test_blocks_github_hooks_file(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "/workspace/project/.github/hooks/check-sensitive-access.sh",
            ["**/.github/hooks/**"],
        )
        self.assertEqual(hit, "**/.github/hooks/**")

    def test_blocks_github_hooks_json(self) -> None:
        hit = copilot_guard.check_blocked_path(
            ".github/hooks/pre-tool-use.json",
            ["**/.github/hooks/**"],
        )
        self.assertEqual(hit, "**/.github/hooks/**")

    def test_blocks_github_hooks_nested_script(self) -> None:
        hit = copilot_guard.check_blocked_path(
            ".github/hooks/scripts/check.sh",
            ["**/.github/hooks/**"],
        )
        self.assertEqual(hit, "**/.github/hooks/**")

    # --- SSH ---

    def test_blocks_ssh_directory(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "/home/user/.ssh/known_hosts",
            ["**/.ssh/*"],
        )
        self.assertEqual(hit, "**/.ssh/*")

    def test_blocks_ssh_config(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "/home/user/.ssh/config",
            ["**/.ssh/*"],
        )
        self.assertEqual(hit, "**/.ssh/*")

    def test_blocks_id_rsa(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "/home/user/.ssh/id_rsa",
            ["**/id_rsa"],
        )
        self.assertEqual(hit, "**/id_rsa")

    def test_blocks_id_ed25519(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "/home/user/.ssh/id_ed25519",
            ["**/id_ed25519"],
        )
        self.assertEqual(hit, "**/id_ed25519")

    def test_blocks_id_ecdsa(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "/home/user/.ssh/id_ecdsa",
            ["**/id_ecdsa"],
        )
        self.assertEqual(hit, "**/id_ecdsa")

    def test_does_not_match_id_rsa_pub(self) -> None:
        hit = copilot_guard.check_blocked_path(
            "/home/user/.ssh/id_rsa.pub",
            ["**/id_rsa"],
        )
        self.assertIsNone(hit)

    # --- Command matching for hook file modification ---

    def test_command_blocks_cat_copilot_hooks(self) -> None:
        hit = copilot_guard.check_blocked_command(
            "cat ~/.copilot/hooks/blocked-files.txt",
            ["**/.copilot/hooks/**"],
        )
        self.assertEqual(hit, "**/.copilot/hooks/**")

    def test_command_blocks_cat_copilot_guard_script(self) -> None:
        """Critical: must block reading the guard script itself."""
        hit = copilot_guard.check_blocked_command(
            "cat ~/.copilot/hooks/scripts/copilot-guard.py",
            ["**/.copilot/hooks/**"],
        )
        self.assertEqual(hit, "**/.copilot/hooks/**")

    def test_command_blocks_sed_modify_guard_script(self) -> None:
        """Critical: must block modification of the guard script."""
        hit = copilot_guard.check_blocked_command(
            "sed -i 's/deny/allow/g' ~/.copilot/hooks/scripts/copilot-guard.py",
            ["**/.copilot/hooks/**"],
        )
        self.assertEqual(hit, "**/.copilot/hooks/**")

    def test_command_blocks_rm_github_hooks(self) -> None:
        hit = copilot_guard.check_blocked_command(
            "rm .github/hooks/check-sensitive-access.sh",
            ["**/.github/hooks/**"],
        )
        self.assertEqual(hit, "**/.github/hooks/**")

    def test_command_blocks_cat_ssh_key(self) -> None:
        hit = copilot_guard.check_blocked_command(
            "cat ~/.ssh/id_ed25519",
            ["**/id_ed25519"],
        )
        self.assertEqual(hit, "**/id_ed25519")

    def test_command_blocks_cat_copilot_mcp_config(self) -> None:
        hit = copilot_guard.check_blocked_command(
            "cat ~/.copilot/mcp-config.json",
            ["**/.copilot/mcp-config.json"],
        )
        self.assertEqual(hit, "**/.copilot/mcp-config.json")


if __name__ == "__main__":
    unittest.main()
