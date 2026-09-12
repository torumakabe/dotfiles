import json
import pathlib
import unittest

from tests._helpers import load_script, run_hook


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT_PATH = (
    REPO_ROOT
    / "home/private_dot_copilot/hooks/scripts/executable_node-global-enforcer.py"
)

nge = load_script("node_global_enforcer", SCRIPT_PATH)


class CommandPolicyTests(unittest.TestCase):
    def _assert_commands(self, commands: tuple[str, ...], blocked: bool) -> None:
        for command in commands:
            with self.subTest(command=command):
                result = nge.check_command(command)
                if blocked:
                    self.assertIsNotNone(result)
                else:
                    self.assertIsNone(result)

    def test_blocks_global_package_operations(self) -> None:
        self._assert_commands(
            (
                "npm install -g typescript",
                "npm i -g typescript",
                "npm install --global typescript",
                "npm add -g typescript",
                "npm -g install typescript",
                "npm install -g typescript eslint",
                "NODE_ENV=production npm install -g foo",
                "npm install --location=global typescript",
                "npm install --location global typescript",
                "npm link -g",
                "npm link",
                "npm link express",
                "npm ln",
                "npm ln express",
                "sudo npm install -g typescript",
                "sudo -E npm install -g typescript",
                "env npm install -g typescript",
                "/usr/bin/npm install -g typescript",
                "/usr/local/bin/npm install -g foo",
                "/usr/bin/env npm install -g foo",
                "/usr/bin/sudo npm install -g foo",
                "sudo -u root npm install -g typescript",
                "sudo -u nobody npm install -g foo",
                "env -u NODE_ENV npm install -g foo",
                "command npm install -g typescript",
                "yarn global add typescript",
                "sudo yarn global add typescript",
                "yarn --silent global add typescript",
                "yarn --cwd /repo global add typescript",
                "pnpm add -g typescript",
                "pnpm install --global typescript",
                "pnpm link --global",
                "bun add -g typescript",
                "bun install --global typescript",
                "corepack yarn global add typescript",
                "corepack pnpm add -g typescript",
            ),
            blocked=True,
        )

    def test_allows_local_and_unrelated_operations(self) -> None:
        self._assert_commands(
            (
                "npm install typescript",
                "npm i",
                "npm install -D typescript",
                "npm ci",
                "npm run build",
                "npm test",
                "npx create-react-app my-app",
                "npm uninstall -g typescript",
                "npm install -- -g typescript",
                "npm install link",
                "npm install ln",
                "npm install foo | tee -g log.txt",
                "yarn add typescript",
                "yarn install",
                "pnpm add typescript",
                "pnpm dlx create-react-app my-app",
                "bun add typescript",
                "bunx create-react-app my-app",
                "",
                "git status",
                "node script.js",
            ),
            blocked=False,
        )

    def test_shell_chains(self) -> None:
        cases = (
            ("echo ok && npm install -g foo", True),
            ("npm install && npm test", False),
            ("echo foo | npm install -g bar", True),
            ("cd /tmp; npm i -g eslint", True),
        )
        for command, blocked in cases:
            with self.subTest(command=command):
                result = nge.check_command(command)
                self.assertEqual(result is not None, blocked)


class MainIntegrationTests(unittest.TestCase):
    def _decision(self, payload: dict | str) -> dict:
        result = run_hook(SCRIPT_PATH, payload)
        self.assertEqual(result.returncode, 0)
        return json.loads(result.stdout)

    def _assert_allowed(self, payload: dict) -> None:
        result = run_hook(SCRIPT_PATH, payload)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_deny_global_install(self) -> None:
        output = self._decision(
            {
                "toolName": "bash",
                "toolArgs": {"command": "npm install -g typescript"},
            }
        )
        self.assertEqual(output["permissionDecision"], "deny")

    def test_allow_local_install(self) -> None:
        self._assert_allowed(
            {
                "toolName": "bash",
                "toolArgs": {"command": "npm install typescript"},
            }
        )

    def test_allow_non_bash_tool(self) -> None:
        self._assert_allowed(
            {
                "toolName": "edit",
                "toolArgs": {"path": "/tmp/foo.txt"},
            }
        )

    def test_invalid_json_denies(self) -> None:
        output = self._decision("not valid json")
        self.assertEqual(output["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
