import json
import pathlib
import tempfile
import unittest
from unittest import mock

from tests._helpers import load_script, run_hook


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "home/private_dot_copilot/hooks/scripts/executable_copilot-guard.py"


copilot_guard = load_script("copilot_guard", SCRIPT_PATH)


# Helper to build a CheckContext for testing.
def make_ctx(
    tool_name: str = "",
    tool_args: dict | None = None,
    command: str = "",
    allowed_patterns: list[str] | None = None,
    blocked_patterns: list[str] | None = None,
    ask_patterns: list[str] | None = None,
) -> "copilot_guard.CheckContext":
    return copilot_guard.CheckContext(
        tool_name=tool_name,
        tool_args=tool_args or {},
        command=command,
        allowed_patterns=allowed_patterns or [],
        blocked_patterns=blocked_patterns or [],
        ask_patterns=ask_patterns or [],
    )


class GuardAssertionsMixin:
    def assert_check_result(
        self, result, decision: str | None, reason_contains: str | None = None
    ) -> None:
        if decision is None:
            self.assertIsNone(result)
            return
        self.assertIsNotNone(result)
        self.assertEqual(result.decision, decision)
        if reason_contains is not None:
            self.assertIn(reason_contains, result.reason)

    def assert_hook_decision(self, result, decision: str | None) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        if decision is None:
            self.assertEqual(result.stdout, "")
            return
        self.assertEqual(json.loads(result.stdout)["permissionDecision"], decision)


class CopilotGuardApplyPatchTests(unittest.TestCase):
    @staticmethod
    def _payload_for_path(tool_name: str, path: pathlib.Path) -> dict:
        if tool_name == "apply_patch":
            return {
                "toolName": tool_name,
                "toolArgs": (
                    "*** Begin Patch\n"
                    f"*** Update File: {path}\n"
                    "*** End Patch\n"
                ),
            }
        return {"toolName": tool_name, "toolArgs": {"path": str(path)}}

    def test_extracts_all_apply_patch_target_paths(self) -> None:
        patch = """*** Begin Patch
*** Add File: docs/new.md
*** Update File: src/app.py
*** Move to: src/main.py
*** Delete File: obsolete.txt
*** End Patch
"""

        self.assertEqual(
            copilot_guard.extract_apply_patch_paths(patch),
            ["docs/new.md", "src/app.py", "src/main.py", "obsolete.txt"],
        )

    def test_allows_unprotected_apply_patch_target(self) -> None:
        result = run_hook(
            SCRIPT_PATH,
            {
                "toolName": "apply_patch",
                "toolArgs": "*** Begin Patch\n*** Update File: docs/readme.md\n*** End Patch\n",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_denies_blocked_apply_patch_target(self) -> None:
        result = run_hook(
            SCRIPT_PATH,
            {
                "toolName": "apply_patch",
                "toolArgs": (
                    "*** Begin Patch\n"
                    "*** Update File: C:\\Users\\me\\.azure\\accessTokens.json\n"
                    "*** End Patch\n"
                ),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        decision = json.loads(result.stdout)
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertTrue(decision["permissionDecisionReason"].startswith("Blocked pattern:"))

    def test_allows_azure_deploy_plan_with_unix_or_windows_separators(self) -> None:
        for tool_name in ("view", "apply_patch", "edit", "create", "write"):
            for path in (".azure/deployment-plan.md", r".azure\deployment-plan.md"):
                with self.subTest(tool_name=tool_name, path=path):
                    payload = self._payload_for_path(tool_name, pathlib.Path(path))
                    payload["cwd"] = str(REPO_ROOT)
                    result = run_hook(SCRIPT_PATH, payload)

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_uses_hook_process_cwd_for_absolute_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir:
            project_root = pathlib.Path(project_dir).resolve()
            plan = project_root / ".azure/deployment-plan.md"

            for tool_name in ("view", "apply_patch", "edit", "create", "write"):
                with self.subTest(tool_name=tool_name):
                    payload = self._payload_for_path(tool_name, plan)
                    payload["cwd"] = str(pathlib.Path.home())
                    result = run_hook(
                        SCRIPT_PATH,
                        payload,
                        cwd=project_root,
                    )

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_denies_plan_when_hook_process_cwd_is_outside_payload_project(self) -> None:
        with tempfile.TemporaryDirectory() as parent_dir:
            parent = pathlib.Path(parent_dir).resolve()
            project_root = parent / "project"
            process_root = parent / "hook-process"
            project_root.mkdir()
            process_root.mkdir()
            plan = project_root / ".azure/deployment-plan.md"

            payload = self._payload_for_path("view", plan)
            payload["cwd"] = str(project_root)
            result = run_hook(SCRIPT_PATH, payload, cwd=process_root)

            self.assertEqual(result.returncode, 0, result.stderr)
            decision = json.loads(result.stdout)
            self.assertEqual(decision["permissionDecision"], "deny")
            self.assertTrue(
                decision["permissionDecisionReason"].startswith("Blocked pattern:")
            )

    def test_allows_absolute_project_azure_deploy_plan_for_file_tools(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir:
            project_root = pathlib.Path(project_dir).resolve()
            plan = project_root / ".azure/deployment-plan.md"

            for tool_name in ("view", "apply_patch", "edit", "create", "write"):
                with self.subTest(tool_name=tool_name):
                    payload = self._payload_for_path(tool_name, plan)
                    payload["cwd"] = str(project_root)
                    result = run_hook(SCRIPT_PATH, payload, cwd=project_root)

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_denies_other_project_azure_files(self) -> None:
        for path in (
            ".azure/config.json",
            ".azure/dev/.env",
            ".azure/dev/notes.txt",
        ):
            for tool_name in ("view", "apply_patch"):
                with self.subTest(path=path, tool_name=tool_name):
                    result = run_hook(
                        SCRIPT_PATH,
                        self._payload_for_path(tool_name, pathlib.Path(path)),
                    )

                    self.assertEqual(result.returncode, 0, result.stderr)
                    decision = json.loads(result.stdout)
                    self.assertEqual(decision["permissionDecision"], "deny")

    def test_denies_home_azure_deployment_plan(self) -> None:
        for path in (
            "/.azure/deployment-plan.md",
            "/home/me/.azure/deployment-plan.md",
            r"C:\Users\me\.azure\deployment-plan.md",
            "file:///.azure/deployment-plan.md",
        ):
            with self.subTest(path=path):
                result = run_hook(
                    SCRIPT_PATH,
                    {
                        "toolName": "apply_patch",
                        "toolArgs": (
                            "*** Begin Patch\n"
                            f"*** Update File: {path}\n"
                            "*** End Patch\n"
                        ),
                    },
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                decision = json.loads(result.stdout)
                self.assertEqual(decision["permissionDecision"], "deny")

    def test_denies_absolute_azure_deploy_plan_outside_project_for_file_tools(self) -> None:
        with tempfile.TemporaryDirectory() as parent_dir:
            parent = pathlib.Path(parent_dir).resolve()
            project_root = parent / "project"
            other_project = parent / "other-project"
            project_root.mkdir()
            other_project.mkdir()
            targets = {
                "home": pathlib.Path.home() / ".azure/deployment-plan.md",
                "other-project": other_project / ".azure/deployment-plan.md",
                "project-parent": parent / ".azure/deployment-plan.md",
            }

            for target_name, target in targets.items():
                for tool_name in ("view", "apply_patch", "edit", "create", "write"):
                    with self.subTest(target=target_name, tool_name=tool_name):
                        payload = self._payload_for_path(tool_name, target)
                        payload["cwd"] = str(project_root)
                        result = run_hook(
                            SCRIPT_PATH,
                            payload,
                            cwd=project_root,
                        )

                        self.assertEqual(result.returncode, 0, result.stderr)
                        decision = json.loads(result.stdout)
                        self.assertEqual(decision["permissionDecision"], "deny")

    def test_denies_absolute_azure_deploy_plan_through_symlink_for_file_tools(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir:
            project_root = pathlib.Path(project_dir).resolve()
            real_azure = project_root / "real-azure"
            real_azure.mkdir()
            azure_link = project_root / ".azure"
            try:
                azure_link.symlink_to(real_azure, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            plan = azure_link / "deployment-plan.md"

            for tool_name in ("view", "apply_patch", "edit", "create", "write"):
                with self.subTest(tool_name=tool_name):
                    payload = self._payload_for_path(tool_name, plan)
                    payload["cwd"] = str(project_root)
                    result = run_hook(
                        SCRIPT_PATH,
                        payload,
                        cwd=project_root,
                    )

                    self.assertEqual(result.returncode, 0, result.stderr)
                    decision = json.loads(result.stdout)
                    self.assertEqual(decision["permissionDecision"], "deny")

    def test_denies_blocked_target_beside_allowed_azure_deploy_plan(self) -> None:
        result = run_hook(
            SCRIPT_PATH,
            {
                "toolName": "apply_patch",
                "toolArgs": (
                    "*** Begin Patch\n"
                    "*** Update File: .azure/deployment-plan.md\n"
                    "*** Add File: .azure/vmpoc-disabled.parameters.json\n"
                    "+{}\n"
                    "*** Add File: .azure/vmpoc-both-one.parameters.json\n"
                    "+{}\n"
                    "*** Add File: .azure/vmpoc-fallback.parameters.json\n"
                    "+{}\n"
                    "*** End Patch\n"
                ),
                "cwd": str(REPO_ROOT),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        decision = json.loads(result.stdout)
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn(".azure/vmpoc-disabled.parameters.json", decision["permissionDecisionReason"])

    def test_denies_allowed_path_for_unrecognized_path_tool(self) -> None:
        result = run_hook(
            SCRIPT_PATH,
            {
                "toolName": "future_path_tool",
                "toolArgs": {"path": ".azure/deployment-plan.md"},
                "cwd": str(REPO_ROOT),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        decision = json.loads(result.stdout)
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn(".azure/deployment-plan.md", decision["permissionDecisionReason"])

    def test_asks_for_protected_hook_apply_patch_target(self) -> None:
        result = run_hook(
            SCRIPT_PATH,
            {
                "toolName": "apply_patch",
                "toolArgs": (
                    "*** Begin Patch\n"
                    "*** Update File: C:\\Users\\me\\.copilot\\hooks\\hooks.json\n"
                    "*** End Patch\n"
                ),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        decision = json.loads(result.stdout)
        self.assertEqual(decision["permissionDecision"], "ask")
        self.assertIn(".copilot/hooks", decision["permissionDecisionReason"])


class CopilotGuardReadOnlySearchTests(unittest.TestCase):
    @staticmethod
    def _run(
        tool_name: str,
        tool_args: dict,
        project_root: pathlib.Path = REPO_ROOT,
    ):
        return run_hook(
            SCRIPT_PATH,
            {
                "toolName": tool_name,
                "toolArgs": tool_args,
                "cwd": str(project_root),
            },
            cwd=project_root,
        )

    def test_allows_rg_allowed_file_in_scalar_or_array_paths(self) -> None:
        paths = (
            ".azure/deployment-plan.md",
            r".azure\deployment-plan.md",
            str(REPO_ROOT / ".azure/deployment-plan.md"),
        )
        for path in paths:
            for value in (path, [path]):
                with self.subTest(path=path, value_type=type(value).__name__):
                    result = self._run("rg", {"pattern": "deployment", "paths": value})

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_allows_glob_exact_allowed_pattern_with_project_roots(self) -> None:
        for pattern in (
            ".azure/deployment-plan.md",
            r".azure\deployment-plan.md",
        ):
            for paths in (None, ".", [str(REPO_ROOT)]):
                with self.subTest(pattern=pattern, paths=paths):
                    tool_args = {"pattern": pattern}
                    if paths is not None:
                        tool_args["paths"] = paths
                    result = self._run("glob", tool_args)

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_does_not_treat_rg_content_pattern_as_a_path(self) -> None:
        result = self._run(
            "rg",
            {
                "pattern": r"\.azure/deployment-plan\.md",
                "paths": "docs",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_denies_blocked_only_paths_for_read_only_search_tools(self) -> None:
        cases = (
            ("rg", {"pattern": "clientSecret", "paths": ".azure/config.json"}),
            ("glob", {"pattern": ".azure/config.json", "paths": "."}),
        )
        for tool_name, tool_args in cases:
            with self.subTest(tool_name=tool_name):
                result = self._run(tool_name, tool_args)

                self.assertEqual(result.returncode, 0, result.stderr)
                decision = json.loads(result.stdout)
                self.assertEqual(decision["permissionDecision"], "deny")

    def test_denies_wildcard_search_filter_in_blocked_area(self) -> None:
        cases = (
            ("rg", {"pattern": "deployment", "paths": ".", "glob": ".azure/**"}),
            ("glob", {"pattern": ".azure/**", "paths": "."}),
        )
        for tool_name, tool_args in cases:
            with self.subTest(tool_name=tool_name):
                result = self._run(tool_name, tool_args)

                self.assertEqual(result.returncode, 0, result.stderr)
                decision = json.loads(result.stdout)
                self.assertEqual(decision["permissionDecision"], "deny")

    def test_denies_exact_allowed_filter_with_outside_search_root(self) -> None:
        with tempfile.TemporaryDirectory() as outside_dir:
            cases = (
                (
                    "rg",
                    {
                        "pattern": "deployment",
                        "paths": [".", outside_dir],
                        "glob": ".azure/deployment-plan.md",
                    },
                ),
                (
                    "glob",
                    {
                        "pattern": ".azure/deployment-plan.md",
                        "paths": [outside_dir],
                    },
                ),
            )
            for tool_name, tool_args in cases:
                with self.subTest(tool_name=tool_name):
                    result = self._run(tool_name, tool_args)

                    self.assertEqual(result.returncode, 0, result.stderr)
                    decision = json.loads(result.stdout)
                    self.assertEqual(decision["permissionDecision"], "deny")

    def test_denies_exact_allowed_filter_with_wildcard_search_root(self) -> None:
        cases = (
            (
                "rg",
                {
                    "pattern": "deployment",
                    "paths": "*",
                    "glob": ".azure/deployment-plan.md",
                },
            ),
            (
                "glob",
                {
                    "pattern": ".azure/deployment-plan.md",
                    "paths": ["*"],
                },
            ),
        )
        for tool_name, tool_args in cases:
            with self.subTest(tool_name=tool_name):
                result = self._run(tool_name, tool_args)

                self.assertEqual(result.returncode, 0, result.stderr)
                decision = json.loads(result.stdout)
                self.assertEqual(decision["permissionDecision"], "deny")

    def test_denies_exact_allowed_filter_with_symlink_search_root(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir:
            project_root = pathlib.Path(project_dir).resolve()
            real_root = project_root / "real-root"
            real_root.mkdir()
            search_root = project_root / "search-root"
            try:
                search_root.symlink_to(real_root, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")

            cases = (
                (
                    "rg",
                    {
                        "pattern": "deployment",
                        "paths": str(search_root),
                        "glob": ".azure/deployment-plan.md",
                    },
                ),
                (
                    "glob",
                    {
                        "pattern": ".azure/deployment-plan.md",
                        "paths": str(search_root),
                    },
                ),
            )
            for tool_name, tool_args in cases:
                with self.subTest(tool_name=tool_name):
                    result = self._run(tool_name, tool_args, project_root)

                    self.assertEqual(result.returncode, 0, result.stderr)
                    decision = json.loads(result.stdout)
                    self.assertEqual(decision["permissionDecision"], "deny")

    def test_denies_allowed_file_with_dotdot_or_file_uri(self) -> None:
        for path in (
            "../project/.azure/deployment-plan.md",
            "file:///.azure/deployment-plan.md",
        ):
            with self.subTest(path=path):
                result = self._run("rg", {"pattern": "deployment", "paths": path})

                self.assertEqual(result.returncode, 0, result.stderr)
                decision = json.loads(result.stdout)
                self.assertEqual(decision["permissionDecision"], "deny")

    def test_denies_allowed_file_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as parent_dir:
            parent = pathlib.Path(parent_dir).resolve()
            project_root = parent / "project"
            other_project = parent / "other-project"
            project_root.mkdir()
            other_project.mkdir()
            target = other_project / ".azure/deployment-plan.md"

            for value in (str(target), [str(target)]):
                with self.subTest(value_type=type(value).__name__):
                    result = self._run(
                        "rg",
                        {"pattern": "deployment", "paths": value},
                        project_root,
                    )

                    self.assertEqual(result.returncode, 0, result.stderr)
                    decision = json.loads(result.stdout)
                    self.assertEqual(decision["permissionDecision"], "deny")

    def test_denies_allowed_file_through_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir:
            project_root = pathlib.Path(project_dir).resolve()
            real_azure = project_root / "real-azure"
            real_azure.mkdir()
            azure_link = project_root / ".azure"
            try:
                azure_link.symlink_to(real_azure, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")

            result = self._run(
                "rg",
                {
                    "pattern": "deployment",
                    "paths": str(azure_link / "deployment-plan.md"),
                },
                project_root,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            decision = json.loads(result.stdout)
            self.assertEqual(decision["permissionDecision"], "deny")

    def test_denies_mixed_allowed_and_blocked_search_paths(self) -> None:
        result = self._run(
            "rg",
            {
                "pattern": "azure",
                "paths": [
                    ".azure/deployment-plan.md",
                    ".azure/config.json",
                ],
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        decision = json.loads(result.stdout)
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn(".azure/config.json", decision["permissionDecisionReason"])

    def test_denies_unrecognized_search_tool_names(self) -> None:
        for tool_name in ("grep", "RG", "Glob"):
            with self.subTest(tool_name=tool_name):
                result = self._run(
                    tool_name,
                    {"paths": ".azure/deployment-plan.md"},
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                decision = json.loads(result.stdout)
                self.assertEqual(decision["permissionDecision"], "deny")


class CopilotGuardPathMatchingTests(unittest.TestCase):
    def test_blocked_path_matching_cases(self) -> None:
        cases = (
            ("substring suffix", "/tmp/accessTokens.json.backup", ["**/accessTokens.json"], None),
            ("windows path", r"C:\Users\me\.azure\accessTokens.json", ["**/accessTokens.json"], "**/accessTokens.json"),
            ("nested unix path", "/home/me/project/.azure/dev/.env", ["**/.azure/**/.env"], "**/.azure/**/.env"),
            ("file URI", "file:///C:/Users/me/.azure/accessTokens.json", ["**/accessTokens.json"], "**/accessTokens.json"),
            ("file URI with netloc", "file://server/share/.azure/accessTokens.json", ["**/accessTokens.json"], "**/accessTokens.json"),
        )
        for name, candidate, patterns, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(
                    copilot_guard.check_blocked_path(candidate, patterns), expected
                )

    def test_allowed_path_rejects_symlinked_azure_directory(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as target_dir:
            project_root = pathlib.Path(project_dir)
            azure_link = project_root / ".azure"
            try:
                azure_link.symlink_to(target_dir, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")

            allowed = copilot_guard.matches_allowed_path(
                ".azure/deployment-plan.md",
                [".azure/deployment-plan.md"],
                project_root,
            )

        self.assertFalse(allowed)

    def test_allowed_path_rejects_wildcard_allowed_pattern(self) -> None:
        self.assertFalse(
            copilot_guard.matches_allowed_path(
                ".azure/deployment-plan.md", [".azure/**"], REPO_ROOT
            )
        )

    def test_project_containment_rejects_junction_component(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir:
            project_root = pathlib.Path(project_dir)
            with (
                mock.patch.object(pathlib.Path, "is_symlink", return_value=False),
                mock.patch.object(pathlib.Path, "is_junction", return_value=True),
            ):
                contained = copilot_guard.is_project_contained_path(
                    "search-root", project_root
                )

        self.assertFalse(contained)


class CopilotGuardCommandMatchingTests(GuardAssertionsMixin, unittest.TestCase):
    def test_command_matching_cases(self) -> None:
        cases = (
            ("non-path substring", 'echo os.environ["PATH"]', ["**/.env"], "bash", None),
            ("windows assignment", 'type --file="C:\\Users\\me\\.azure\\accessTokens.json"', ["**/accessTokens.json"], "bash", "**/accessTokens.json"),
            ("windows path with spaces", 'type --file="C:\\Users\\John Doe\\.azure\\accessTokens.json"', ["**/accessTokens.json"], "bash", "**/accessTokens.json"),
            ("no file-tool exception", "type .azure/deployment-plan.md", ["**/.azure/**"], "bash", "**/.azure/**"),
            ("bash adjacent empty quotes", "cat .e''nv", ["**/.env"], "bash", "**/.env"),
            ("bash adjacent double quotes", 'cat .e""nv', ["**/.env"], "bash", "**/.env"),
            ("bash split command and path", "c'a't '.e'nv", ["**/.env"], "bash", "**/.env"),
            ("bash mixed quote fragments", """c"a"t .e'n'"v" """, ["**/.env"], "bash", "**/.env"),
            ("PowerShell adjacent double quote", 'Get-Content .en"v"', ["**/.env"], "powershell", "**/.env"),
            ("PowerShell adjacent single quote", "Get-Content .en'v'", ["**/.env"], "powershell", "**/.env"),
            ("PowerShell split command", 'Get-"Content" .e"n"v', ["**/.env"], "powershell", "**/.env"),
            ("bash unbalanced quote", 'cat .e"nv', ["**/.env"], "bash", "**/.env"),
            ("PowerShell unbalanced quote", 'Get-Content .e"nv', ["**/.env"], "powershell", "**/.env"),
        )
        for name, command, patterns, shell, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(
                    copilot_guard.check_blocked_command(command, patterns, shell),
                    expected,
                )

    def test_entrypoint_quote_handling_cases(self) -> None:
        cases = (
            ("bash", "cat .e''nv", "deny"),
            ("bash", """c"a"t .e'n'"v" """, "deny"),
            ("powershell", 'Get-Content .en"v"', "deny"),
            ("powershell", "Get-Content .en'v'", "deny"),
            ("bash", "cat <<'EOF'\nit's ordinary text\nEOF", None),
            ("bash", "printf '%s\n ordinary", None),
        )
        for shell, command, expected in cases:
            with self.subTest(shell=shell, command=command):
                result = run_hook(
                    SCRIPT_PATH,
                    {"toolName": shell, "toolArgs": {"command": command}},
                )
                self.assert_hook_decision(result, expected)

    def test_punctuation_only_tokens_are_ignored_exhaustively(self) -> None:
        self.assertEqual(
            copilot_guard.extract_command_candidates(
                "echo ok ;&|()<> &&||",
                "bash",
            ),
            ["echo", "ok"],
        )

    def test_command_cannot_change_to_home_before_using_exception_path(self) -> None:
        result = run_hook(
            SCRIPT_PATH,
            {
                "toolName": "powershell",
                "toolArgs": {
                    "command": "Set-Location ~; Get-Content .azure/deployment-plan.md",
                },
            },
        )
        self.assert_hook_decision(result, "deny")


class CopilotGuardEnvBlockingTests(GuardAssertionsMixin, unittest.TestCase):
    """Tests for environment variable access blocking."""

    def test_environment_access_cases(self) -> None:
        denied = (
            ("printenv", "bash", "printenv"),
            ("printenv pipe", "bash", "printenv | grep SECRET"),
            ("bare env", "bash", "env"),
            ("bare set", "bash", "set"),
            ("declare", "bash", "declare -p"),
            ("export", "bash", "export -p"),
            ("compgen variables", "bash", "compgen -v"),
            ("compgen environment", "bash", "compgen -e"),
            ("quoted set", "bash", '"s"et'),
            ("quoted declare", "bash", 'dec"lare" -p'),
            ("quoted export", "bash", 'expo"rt" -p'),
            ("quoted compgen", "bash", 'comp"gen" -v'),
            ("quoted PowerShell double", "powershell", 'Get-Ch"ildItem" Env:'),
            ("quoted PowerShell single", "powershell", "Get-Ch'ildItem' Env:"),
            ("POSIX empty quotes", "bash", "print''env"),
            ("POSIX double quotes", "bash", 'print""env'),
            ("POSIX split single quotes", "bash", "pr'int'en'v'"),
            ("POSIX mixed quotes", "bash", """pr"in"t'e'nv"""),
            ("GitHub token", "bash", "echo $GITHUB_TOKEN"),
            ("braced secret", "bash", "echo ${SECRET_KEY}"),
            ("Azure secret", "bash", 'echo "$AZURE_CLIENT_SECRET"'),
            ("API key", "bash", "curl -H 'Authorization: $API_KEY'"),
            ("database password", "bash", "mysql -p$DB_PASSWORD"),
            ("connection string", "bash", "echo $DATABASE_CONNECTION_STRING"),
            ("auth token", "bash", "echo $AUTH_TOKEN"),
            ("camel auth token", "bash", "echo $githubToken"),
            ("camel API key", "bash", "echo $apiKey"),
            ("concatenated secret", "bash", "echo $mysecret"),
            ("concatenated token", "bash", "echo $githubtoken"),
            ("concatenated password", "bash", "echo $mypassword"),
            ("concatenated API key", "bash", "echo $XAPIKEY"),
            ("concatenated signing key", "bash", "echo $signingkey"),
            ("PowerShell env", "powershell", "Write-Output $env:GITHUB_TOKEN"),
            ("braced PowerShell env", "powershell", "Write-Output ${env:GITHUB_TOKEN}"),
            ("Python environ", "bash", 'uv run python -c "import os; print(os.environ)"'),
            ("Node process.env", "bash", 'node -e "console.log(process.env)"'),
            ("quoted Node process.env", "bash", "node -e 'console.log(process.'env')'"),
            ("Perl ENV", "bash", "perl -e 'foreach (keys %ENV) { print }'"),
            ("Ruby ENV", "bash", 'ruby -e "puts ENV.to_h"'),
            ("PowerShell env dump", "powershell", "Get-ChildItem Env:"),
            ("pipe chain", "bash", "ls && printenv | grep SECRET"),
            ("sensitive chained variable", "bash", "cd /tmp && echo $GITHUB_TOKEN"),
        )
        allowed = (
            ("env isolated", "bash", "env -i PATH=/usr/bin bash"),
            ("env unset", "bash", "env -u SECRET command"),
            ("env assignment", "bash", "env FOO=bar command"),
            ("env separator", "bash", "env -- command"),
            ("set option", "bash", "set -e"),
            ("set options", "bash", "set -euo pipefail"),
            ("author", "bash", "echo $author"),
            ("keyword", "bash", "echo $keyword"),
            ("tokens", "bash", "echo $tokens"),
            ("monkey", "bash", "echo $monkey"),
            ("PowerShell local variable", "powershell", "Write-Output $GITHUB_TOKEN"),
            ("PowerShell PATH", "powershell", "Write-Output $env:PATH"),
            ("braced PowerShell PATH", "powershell", "Write-Output ${env:PATH}"),
            ("PATH", "bash", "echo $PATH"),
            ("HOME", "bash", "echo $HOME"),
            ("SHELL", "bash", "echo $SHELL"),
            ("USER", "bash", "echo $USER"),
            ("NODE_ENV", "bash", "echo $NODE_ENV"),
            ("EDITOR", "bash", "echo $EDITOR"),
            ("SSH_AUTH_SOCK", "bash", "echo $SSH_AUTH_SOCK"),
            ("XDG_CONFIG_HOME", "bash", "echo $XDG_CONFIG_HOME"),
            ("TMPDIR", "bash", "echo $TMPDIR"),
            ("PWD", "bash", "echo $PWD"),
            ("empty", "bash", ""),
            ("normal command", "bash", "ls -la /tmp"),
            ("ordinary heredoc", "bash", "cat <<'EOF'\nit's ordinary text\nEOF"),
            ("unbalanced quote", "bash", "printf '%s\n ordinary"),
            ("git", "bash", "git --no-pager status"),
        )
        for expected, cases in ((True, denied), (False, allowed)):
            for name, shell, command in cases:
                with self.subTest(name=name):
                    result = copilot_guard.check_env_access(command, shell)
                    self.assertEqual(result is not None, expected)

    def test_entrypoint_denies_quote_obfuscated_env_dump(self) -> None:
        for command in ("print''env", """pr"in"t'e'nv"""):
            with self.subTest(command=command):
                result = run_hook(
                    SCRIPT_PATH,
                    {"toolName": "bash", "toolArgs": {"command": command}},
                )
                self.assert_hook_decision(result, "deny")



class CopilotGuardNewBlockedPatternsTests(unittest.TestCase):
    """Coverage for Copilot hooks, SSH, and .github hook patterns."""

    def test_new_blocked_path_patterns(self) -> None:
        cases = (
            ("copilot hook", "/home/user/.copilot/hooks/hooks.json", "**/.copilot/hooks/**"),
            ("blocked config", "/home/user/.copilot/hooks/blocked-files.txt", "**/.copilot/hooks/**"),
            ("guard script", "/home/user/.copilot/hooks/scripts/copilot-guard.py", "**/.copilot/hooks/**"),
            ("audit script", "/home/user/.copilot/hooks/scripts/audit-log.py", "**/.copilot/hooks/**"),
            ("MCP config", "/home/user/.copilot/mcp-config.json", "**/.copilot/mcp-config.json"),
            ("Copilot config", "/home/user/.copilot/config.json", "**/.copilot/config.json"),
            ("GitHub hook", "/workspace/project/.github/hooks/check-sensitive-access.sh", "**/.github/hooks/**"),
            ("relative GitHub hook", ".github/hooks/pre-tool-use.json", "**/.github/hooks/**"),
            ("nested GitHub hook", ".github/hooks/scripts/check.sh", "**/.github/hooks/**"),
            ("SSH known hosts", "/home/user/.ssh/known_hosts", "**/.ssh/*"),
            ("SSH config", "/home/user/.ssh/config", "**/.ssh/*"),
            ("RSA key", "/home/user/.ssh/id_rsa", "**/id_rsa"),
            ("Ed25519 key", "/home/user/.ssh/id_ed25519", "**/id_ed25519"),
            ("ECDSA key", "/home/user/.ssh/id_ecdsa", "**/id_ecdsa"),
        )
        for name, candidate, pattern in cases:
            with self.subTest(name=name):
                self.assertEqual(
                    copilot_guard.check_blocked_path(candidate, [pattern]), pattern
                )
        self.assertIsNone(
            copilot_guard.check_blocked_path(
                "/home/user/.ssh/id_rsa.pub", ["**/id_rsa"]
            )
        )

    def test_new_blocked_command_patterns(self) -> None:
        cases = (
            ("hook config", "cat ~/.copilot/hooks/blocked-files.txt", "**/.copilot/hooks/**"),
            ("read guard", "cat ~/.copilot/hooks/scripts/copilot-guard.py", "**/.copilot/hooks/**"),
            ("modify guard", "sed -i 's/deny/allow/g' ~/.copilot/hooks/scripts/copilot-guard.py", "**/.copilot/hooks/**"),
            ("remove GitHub hook", "rm .github/hooks/check-sensitive-access.sh", "**/.github/hooks/**"),
            ("SSH key", "cat ~/.ssh/id_ed25519", "**/id_ed25519"),
            ("MCP config", "cat ~/.copilot/mcp-config.json", "**/.copilot/mcp-config.json"),
        )
        for name, command, pattern in cases:
            with self.subTest(name=name):
                self.assertEqual(
                    copilot_guard.check_blocked_command(command, [pattern]), pattern
                )



class CopilotGuardCheckResultTests(unittest.TestCase):
    def test_check_result_fields(self) -> None:
        for decision, reason in (("deny", "test reason"), ("ask", "confirm this")):
            with self.subTest(decision=decision):
                result = copilot_guard.CheckResult(decision, reason)
                self.assertEqual((result.decision, result.reason), (decision, reason))


class CopilotGuardAskPatternsTests(GuardAssertionsMixin, unittest.TestCase):
    def test_blocked_and_ask_pattern_cases(self) -> None:
        cases = (
            ("ask path", make_ctx(tool_name="edit", tool_args={"path": "/home/user/.copilot/hooks/hooks.json"}, ask_patterns=["**/.copilot/hooks/**"]), "ask", "**/.copilot/hooks/**"),
            ("deny path", make_ctx(tool_name="view", tool_args={"path": "/home/user/.ssh/id_rsa"}, blocked_patterns=["**/id_rsa"]), "deny", None),
            ("deny paths array", make_ctx(tool_name="view", tool_args={"paths": ["/home/user/project/README.md", r"C:\Users\me\.azure\accessTokens.json"]}, blocked_patterns=["**/accessTokens.json"]), "deny", None),
            ("ask paths array", make_ctx(tool_name="edit", tool_args={"paths": ["/home/user/project/README.md", "/home/user/.copilot/hooks/hooks.json"]}, ask_patterns=["**/.copilot/hooks/**"]), "ask", None),
            ("deny priority", make_ctx(tool_name="edit", tool_args={"path": "/home/user/.copilot/hooks/hooks.json"}, blocked_patterns=["**/.copilot/hooks/**"], ask_patterns=["**/.copilot/hooks/**"]), "deny", None),
            ("no match", make_ctx(tool_name="view", tool_args={"path": "/home/user/project/src/main.py"}, blocked_patterns=["**/id_rsa"], ask_patterns=["**/.copilot/hooks/**"]), None, None),
            ("ask command", make_ctx(tool_name="bash", tool_args={"command": "cat ~/.copilot/hooks/hooks.json"}, command="cat ~/.copilot/hooks/hooks.json", ask_patterns=["**/.copilot/hooks/**"]), "ask", None),
            ("terraform vars", make_ctx(tool_name="edit", tool_args={"path": "/project/infra/terraform.tfvars"}, ask_patterns=["**/terraform.tfvars"]), "ask", None),
            ("Bicep parameters", make_ctx(tool_name="view", tool_args={"path": "/project/infra/main.bicepparam"}, ask_patterns=["**/*.bicepparam"]), "ask", None),
            ("MCP config", make_ctx(tool_name="edit", tool_args={"path": "/home/user/.copilot/mcp-config.json"}, ask_patterns=["**/.copilot/mcp-config.json"]), "ask", None),
            ("Copilot config", make_ctx(tool_name="view", tool_args={"path": "/home/user/.copilot/config.json"}, ask_patterns=["**/.copilot/config.json"]), "ask", None),
            ("GitHub hooks", make_ctx(tool_name="edit", tool_args={"path": "/workspace/.github/hooks/policy.json"}, ask_patterns=["**/.github/hooks/**"]), "ask", None),
            ("empty ask patterns", make_ctx(tool_name="edit", tool_args={"path": "/project/terraform.tfvars"}, ask_patterns=[]), None, None),
        )
        for name, ctx, decision, reason in cases:
            with self.subTest(name=name):
                self.assert_check_result(
                    copilot_guard.check_blocked_files(ctx), decision, reason
                )


class CopilotGuardCheckerReturnTypeTests(GuardAssertionsMixin, unittest.TestCase):
    def test_check_env_return_cases(self) -> None:
        cases = (
            ("dump", "bash", "printenv", "deny"),
            ("safe", "bash", "ls -la", None),
            ("PowerShell local", "powershell", "Write-Output $GITHUB_TOKEN", None),
            ("PowerShell env", "powershell", "Write-Output $env:GITHUB_TOKEN", "deny"),
        )
        for name, tool_name, command, decision in cases:
            with self.subTest(name=name):
                result = copilot_guard.check_env(
                    make_ctx(
                        tool_name=tool_name,
                        tool_args={"command": command},
                        command=command,
                    )
                )
                self.assert_check_result(result, decision)
                if result is not None:
                    self.assertIsInstance(result, copilot_guard.CheckResult)


class GitCommitCheckerTests(GuardAssertionsMixin, unittest.TestCase):
    def test_git_commit_detection_cases(self) -> None:
        cases = (
            ("bare", "bash", "git commit"),
            ("message", "bash", 'git commit -m "feat: add feature"'),
            ("quoted bash", "bash", 'git "commit" -m x'),
            ("quoted PowerShell double", "powershell", 'git "commit" -m x'),
            ("quoted PowerShell single", "powershell", "git 'commit' -m x"),
            ("amend", "bash", "git commit --amend"),
            ("global option", "bash", 'git -c user.name=test commit -m "msg"'),
            ("working directory", "bash", "git -C /tmp/repo commit"),
            ("chain", "bash", 'git add . && git commit -m "msg"'),
            ("environment assignment", "bash", 'GIT_AUTHOR_NAME=bot git commit -m "msg"'),
            ("PowerShell", "powershell", 'git commit -m "msg"'),
            ("pipe", "bash", 'echo ok | git commit --allow-empty -m "msg"'),
            ("env wrapper", "bash", "env GIT_AUTHOR_NAME=bot git commit -m msg"),
            ("command wrapper", "bash", "command git commit -m msg"),
            ("absolute path", "bash", "/usr/bin/git commit -m msg"),
            ("Windows executable", "powershell", "git.exe commit -m msg"),
            ("sudo", "bash", "sudo git commit -m msg"),
            ("env flags", "bash", "env -i git commit -m msg"),
        )
        for name, tool_name, command in cases:
            with self.subTest(name=name):
                ctx = make_ctx(
                    tool_name=tool_name,
                    command=command,
                    tool_args={"command": command},
                )
                self.assert_check_result(copilot_guard.check_git_commit(ctx), "ask")

    def test_git_commit_non_matching_cases(self) -> None:
        cases = (
            ("add", "bash", "git add ."),
            ("status", "bash", "git status"),
            ("log", "bash", "git log --oneline"),
            ("diff", "bash", "git --no-pager diff"),
            ("non-shell tool", "edit", "git commit"),
            ("empty", "bash", ""),
            ("echo", "bash", 'echo "git commit"'),
            ("quoted semicolon", "bash", 'echo "test; git commit -m msg"'),
            ("quoted ampersand", "bash", 'echo "foo && git commit"'),
        )
        for name, tool_name, command in cases:
            with self.subTest(name=name):
                ctx = make_ctx(
                    tool_name=tool_name,
                    command=command,
                    tool_args={"command": command},
                )
                self.assert_check_result(copilot_guard.check_git_commit(ctx), None)

    def test_has_git_commit_helper_cases(self) -> None:
        cases = (
            ("git commit", True),
            ("git commit -m 'msg'", True),
            ("git -c k=v commit", True),
            ("git add .", False),
            ("git push", False),
            ("echo git commit", False),
        )
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(copilot_guard._has_git_commit(command), expected)


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

    def test_logs_url_field_for_fetch_tool(self) -> None:
        ctx = make_ctx(
            tool_name="web_fetch",
            tool_args={"url": "https://pastebin.com/abc"},
        )
        copilot_guard._log_deny(ctx, "test deny")
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