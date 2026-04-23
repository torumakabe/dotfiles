import importlib.util
import json
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


# Helper to build a CheckContext for testing.
def make_ctx(
    tool_name: str = "",
    tool_args: dict | None = None,
    command: str = "",
    blocked_patterns: list[str] | None = None,
    ask_patterns: list[str] | None = None,
    allowed_domains: list[str] | None = None,
) -> "copilot_guard.CheckContext":
    return copilot_guard.CheckContext(
        tool_name=tool_name,
        tool_args=tool_args or {},
        command=command,
        blocked_patterns=blocked_patterns or [],
        ask_patterns=ask_patterns or [],
        allowed_domains=allowed_domains or [],
    )


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


class CopilotGuardCheckResultTests(unittest.TestCase):
    """Tests for the CheckResult type and ask() output helper."""

    def test_check_result_is_named_tuple(self) -> None:
        result = copilot_guard.CheckResult("deny", "test reason")
        self.assertEqual(result.decision, "deny")
        self.assertEqual(result.reason, "test reason")

    def test_check_result_ask(self) -> None:
        result = copilot_guard.CheckResult("ask", "confirm this")
        self.assertEqual(result.decision, "ask")
        self.assertEqual(result.reason, "confirm this")


class CopilotGuardAskPatternsTests(unittest.TestCase):
    """Tests for ask-files.txt pattern matching via check_blocked_files."""

    def test_ask_pattern_returns_ask_decision(self) -> None:
        ctx = make_ctx(
            tool_name="edit",
            tool_args={"path": "/home/user/.copilot/hooks/hooks.json"},
            ask_patterns=["**/.copilot/hooks/**"],
        )
        result = copilot_guard.check_blocked_files(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")
        self.assertIn("**/.copilot/hooks/**", result.reason)

    def test_blocked_pattern_returns_deny_decision(self) -> None:
        ctx = make_ctx(
            tool_name="view",
            tool_args={"path": "/home/user/.ssh/id_rsa"},
            blocked_patterns=["**/id_rsa"],
        )
        result = copilot_guard.check_blocked_files(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "deny")

    def test_deny_takes_priority_over_ask_same_file(self) -> None:
        """When a path matches both blocked and ask patterns, deny wins."""
        ctx = make_ctx(
            tool_name="edit",
            tool_args={"path": "/home/user/.copilot/hooks/hooks.json"},
            blocked_patterns=["**/.copilot/hooks/**"],
            ask_patterns=["**/.copilot/hooks/**"],
        )
        result = copilot_guard.check_blocked_files(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "deny")

    def test_no_match_returns_none(self) -> None:
        ctx = make_ctx(
            tool_name="view",
            tool_args={"path": "/home/user/project/src/main.py"},
            blocked_patterns=["**/id_rsa"],
            ask_patterns=["**/.copilot/hooks/**"],
        )
        result = copilot_guard.check_blocked_files(ctx)
        self.assertIsNone(result)

    def test_ask_pattern_command_matching(self) -> None:
        ctx = make_ctx(
            tool_name="bash",
            tool_args={"command": "cat ~/.copilot/hooks/hooks.json"},
            command="cat ~/.copilot/hooks/hooks.json",
            ask_patterns=["**/.copilot/hooks/**"],
        )
        result = copilot_guard.check_blocked_files(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_ask_pattern_terraform_tfvars(self) -> None:
        ctx = make_ctx(
            tool_name="edit",
            tool_args={"path": "/project/infra/terraform.tfvars"},
            ask_patterns=["**/terraform.tfvars"],
        )
        result = copilot_guard.check_blocked_files(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_ask_pattern_bicepparam(self) -> None:
        ctx = make_ctx(
            tool_name="view",
            tool_args={"path": "/project/infra/main.bicepparam"},
            ask_patterns=["**/*.bicepparam"],
        )
        result = copilot_guard.check_blocked_files(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_ask_copilot_mcp_config(self) -> None:
        ctx = make_ctx(
            tool_name="edit",
            tool_args={"path": "/home/user/.copilot/mcp-config.json"},
            ask_patterns=["**/.copilot/mcp-config.json"],
        )
        result = copilot_guard.check_blocked_files(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_ask_copilot_config_json(self) -> None:
        ctx = make_ctx(
            tool_name="view",
            tool_args={"path": "/home/user/.copilot/config.json"},
            ask_patterns=["**/.copilot/config.json"],
        )
        result = copilot_guard.check_blocked_files(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_ask_github_hooks(self) -> None:
        ctx = make_ctx(
            tool_name="edit",
            tool_args={"path": "/workspace/.github/hooks/policy.json"},
            ask_patterns=["**/.github/hooks/**"],
        )
        result = copilot_guard.check_blocked_files(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_empty_ask_patterns_skips(self) -> None:
        ctx = make_ctx(
            tool_name="edit",
            tool_args={"path": "/project/terraform.tfvars"},
            ask_patterns=[],
        )
        result = copilot_guard.check_blocked_files(ctx)
        self.assertIsNone(result)


class CopilotGuardCheckerReturnTypeTests(unittest.TestCase):
    """Tests that existing checkers now return CheckResult instead of raw str."""

    def test_check_env_returns_check_result(self) -> None:
        ctx = make_ctx(
            tool_name="bash",
            tool_args={"command": "printenv"},
            command="printenv",
        )
        result = copilot_guard.check_env(ctx)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, copilot_guard.CheckResult)
        self.assertEqual(result.decision, "deny")

    def test_check_env_returns_none_for_safe(self) -> None:
        ctx = make_ctx(
            tool_name="bash",
            tool_args={"command": "ls -la"},
            command="ls -la",
        )
        result = copilot_guard.check_env(ctx)
        self.assertIsNone(result)

    def test_check_url_returns_check_result(self) -> None:
        ctx = make_ctx(
            tool_name="web_fetch",
            tool_args={"url": "https://evil.example.com"},
            allowed_domains=["github.com"],
        )
        result = copilot_guard.check_url_allowlist(ctx)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, copilot_guard.CheckResult)
        self.assertEqual(result.decision, "deny")


class GitCommitCheckerTests(unittest.TestCase):
    """Tests for the git commit approval checker."""

    # --- Positive cases: should require approval ---

    def test_bare_git_commit(self) -> None:
        ctx = make_ctx(tool_name="bash", command="git commit", tool_args={"command": "git commit"})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_git_commit_with_message(self) -> None:
        ctx = make_ctx(tool_name="bash", command='git commit -m "feat: add feature"', tool_args={"command": 'git commit -m "feat: add feature"'})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_git_commit_amend(self) -> None:
        ctx = make_ctx(tool_name="bash", command="git commit --amend", tool_args={"command": "git commit --amend"})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_git_commit_with_global_option(self) -> None:
        ctx = make_ctx(tool_name="bash", command='git -c user.name=test commit -m "msg"', tool_args={"command": 'git -c user.name=test commit -m "msg"'})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_git_commit_with_C_option(self) -> None:
        ctx = make_ctx(tool_name="bash", command="git -C /tmp/repo commit", tool_args={"command": "git -C /tmp/repo commit"})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_git_commit_in_chain(self) -> None:
        ctx = make_ctx(tool_name="bash", command='git add . && git commit -m "msg"', tool_args={"command": 'git add . && git commit -m "msg"'})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_git_commit_with_env_vars(self) -> None:
        ctx = make_ctx(tool_name="bash", command='GIT_AUTHOR_NAME=bot git commit -m "msg"', tool_args={"command": 'GIT_AUTHOR_NAME=bot git commit -m "msg"'})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_powershell_git_commit(self) -> None:
        ctx = make_ctx(tool_name="powershell", command='git commit -m "msg"', tool_args={"command": 'git commit -m "msg"'})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_git_commit_after_pipe(self) -> None:
        ctx = make_ctx(tool_name="bash", command='echo ok | git commit --allow-empty -m "msg"', tool_args={"command": 'echo ok | git commit --allow-empty -m "msg"'})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    # --- Negative cases: should NOT trigger ---

    def test_git_add_no_match(self) -> None:
        ctx = make_ctx(tool_name="bash", command="git add .", tool_args={"command": "git add ."})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNone(result)

    def test_git_status_no_match(self) -> None:
        ctx = make_ctx(tool_name="bash", command="git status", tool_args={"command": "git status"})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNone(result)

    def test_git_log_no_match(self) -> None:
        ctx = make_ctx(tool_name="bash", command="git log --oneline", tool_args={"command": "git log --oneline"})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNone(result)

    def test_git_diff_no_match(self) -> None:
        ctx = make_ctx(tool_name="bash", command="git --no-pager diff", tool_args={"command": "git --no-pager diff"})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNone(result)

    def test_non_bash_tool_no_match(self) -> None:
        ctx = make_ctx(tool_name="edit", command="git commit", tool_args={"command": "git commit"})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNone(result)

    def test_empty_command_no_match(self) -> None:
        ctx = make_ctx(tool_name="bash", command="", tool_args={"command": ""})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNone(result)

    def test_echo_git_commit_no_match(self) -> None:
        ctx = make_ctx(tool_name="bash", command='echo "git commit"', tool_args={"command": 'echo "git commit"'})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNone(result)

    def test_has_git_commit_helper(self) -> None:
        """Direct unit test for the _has_git_commit helper."""
        self.assertTrue(copilot_guard._has_git_commit("git commit"))
        self.assertTrue(copilot_guard._has_git_commit("git commit -m 'msg'"))
        self.assertTrue(copilot_guard._has_git_commit("git -c k=v commit"))
        self.assertFalse(copilot_guard._has_git_commit("git add ."))
        self.assertFalse(copilot_guard._has_git_commit("git push"))
        self.assertFalse(copilot_guard._has_git_commit("echo git commit"))

    # --- Bypass resistance (GPT 5.4 review findings) ---

    def test_env_wrapper_git_commit(self) -> None:
        ctx = make_ctx(tool_name="bash", command="env GIT_AUTHOR_NAME=bot git commit -m msg", tool_args={"command": "env GIT_AUTHOR_NAME=bot git commit -m msg"})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_command_wrapper_git_commit(self) -> None:
        ctx = make_ctx(tool_name="bash", command="command git commit -m msg", tool_args={"command": "command git commit -m msg"})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_absolute_path_git_commit(self) -> None:
        ctx = make_ctx(tool_name="bash", command="/usr/bin/git commit -m msg", tool_args={"command": "/usr/bin/git commit -m msg"})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_git_exe_commit(self) -> None:
        ctx = make_ctx(tool_name="powershell", command="git.exe commit -m msg", tool_args={"command": "git.exe commit -m msg"})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_sudo_git_commit(self) -> None:
        ctx = make_ctx(tool_name="bash", command="sudo git commit -m msg", tool_args={"command": "sudo git commit -m msg"})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    def test_env_with_flags_git_commit(self) -> None:
        ctx = make_ctx(tool_name="bash", command="env -i git commit -m msg", tool_args={"command": "env -i git commit -m msg"})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "ask")

    # --- False-positive resistance (Opus 4.6 review findings) ---

    def test_quoted_semicolon_git_commit_no_match(self) -> None:
        """Operators inside quotes must not trigger false positives."""
        ctx = make_ctx(tool_name="bash", command='echo "test; git commit -m msg"', tool_args={"command": 'echo "test; git commit -m msg"'})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNone(result)

    def test_quoted_ampersand_git_commit_no_match(self) -> None:
        ctx = make_ctx(tool_name="bash", command='echo "foo && git commit"', tool_args={"command": 'echo "foo && git commit"'})
        result = copilot_guard.check_git_commit(ctx)
        self.assertIsNone(result)


class LogDenyTests(unittest.TestCase):
    """Verify _log_deny captures enough detail to identify the denied target."""

    def setUp(self) -> None:
        import os, tempfile
        self.tmpdir = tempfile.mkdtemp()
        self._orig_env = os.environ.get("COPILOT_AUDIT_DIR")
        os.environ["COPILOT_AUDIT_DIR"] = self.tmpdir
        self.log_file = pathlib.Path(self.tmpdir) / "audit-denies.jsonl"

    def tearDown(self) -> None:
        import os, shutil
        if self._orig_env is None:
            os.environ.pop("COPILOT_AUDIT_DIR", None)
        else:
            os.environ["COPILOT_AUDIT_DIR"] = self._orig_env
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _read_entry(self) -> dict:
        line = self.log_file.read_text(encoding="utf-8").strip()
        return json.loads(line)

    def test_logs_shell_command(self) -> None:
        ctx = make_ctx(tool_name="powershell", command="printenv PATH")
        copilot_guard._log_deny(ctx, "Blocked env dump command: printenv")
        entry = self._read_entry()
        self.assertEqual(entry["tool"], "powershell")
        self.assertEqual(entry["command"], "printenv PATH")
        self.assertIn("env dump", entry["reason"])

    def test_logs_view_tool_path(self) -> None:
        ctx = make_ctx(
            tool_name="view",
            tool_args={"path": "C:\\Users\\me\\.azure\\config"},
        )
        copilot_guard._log_deny(ctx, "Blocked pattern: **/.azure/*")
        entry = self._read_entry()
        self.assertEqual(entry["tool"], "view")
        self.assertEqual(entry["path"], "C:\\Users\\me\\.azure\\config")
        self.assertNotIn("command", entry)

    def test_logs_url_for_fetch_tool(self) -> None:
        ctx = make_ctx(
            tool_name="web_fetch",
            tool_args={"url": "https://pastebin.com/abc"},
        )
        copilot_guard._log_deny(ctx, "URL not in allowlist")
        entry = self._read_entry()
        self.assertEqual(entry["url"], "https://pastebin.com/abc")

    def test_redacts_secrets_in_command(self) -> None:
        ctx = make_ctx(
            tool_name="powershell",
            command="curl -H 'Authorization: Bearer ghp_abc123xyz' https://api.github.com",  # gitleaks:allow
        )
        copilot_guard._log_deny(ctx, "test")
        entry = self._read_entry()
        self.assertIn("[REDACTED]", entry["command"])
        self.assertNotIn("ghp_abc123xyz", entry["command"])

    def test_never_raises_on_unwritable_dir(self) -> None:
        import os
        # Point to a path that can't be a directory (a file blocking mkdir)
        blocker = pathlib.Path(self.tmpdir) / "blocker"
        blocker.write_text("x")
        os.environ["COPILOT_AUDIT_DIR"] = str(blocker)
        ctx = make_ctx(tool_name="bash", command="x")
        copilot_guard._log_deny(ctx, "reason")  # must not raise


if __name__ == "__main__":
    unittest.main()