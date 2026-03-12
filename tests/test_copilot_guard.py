import importlib.util
import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "home/private_dot_copilot/hooks/scripts/executable_copilot-guard.py"


def load_module():
    spec = importlib.util.spec_from_file_location("copilot_guard", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
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


if __name__ == "__main__":
    unittest.main()
