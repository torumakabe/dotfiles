"""Verify the hook scripts keep their duplicated helpers identical.

Each script under home/private_dot_copilot/hooks/scripts is a
self-contained `uv run` script (ADR-007), so shared helpers are copied
into every script instead of being imported from a common module. The
copies are intentional; drifting copies are not. This test fails when one
copy is edited without the others.

Helpers that are deliberately different are not compared here:
  - _PREFIX_COMMANDS: node-global-enforcer also treats `corepack` as a prefix.
  - parse_tool_args vs _parse_tool_args: the enforcers reject malformed or
    non-object values so main() fails safe with a deny, while the audit hooks
    fall back to {} so logging never drops a record.
  - _REDACT_PATTERNS: already covered by test_audit_redaction_sync.py.
"""
import inspect
import json
import pathlib
import unittest

from tests._helpers import load_script, run_hook


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "home/private_dot_copilot/hooks/scripts"


class HookHelperSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.guard = load_script("copilot_guard", SCRIPTS_DIR / "executable_copilot-guard.py")
        cls.node = load_script(
            "node_global_enforcer", SCRIPTS_DIR / "executable_node-global-enforcer.py"
        )
        cls.uv = load_script("uv_enforcer", SCRIPTS_DIR / "executable_uv-enforcer.py")
        cls.audit_log = load_script("audit_log", SCRIPTS_DIR / "executable_audit-log.py")
        cls.audit_failure = load_script(
            "audit_failure", SCRIPTS_DIR / "executable_audit-failure.py"
        )

    def _assert_same_source(self, name: str, *modules) -> None:
        sources = [inspect.getsource(getattr(module, name)) for module in modules]
        for other in sources[1:]:
            self.assertEqual(sources[0], other, f"{name}() drifted between hook scripts")

    def test_enforcer_helpers_identical(self) -> None:
        for name in ("deny", "read_input", "parse_tool_args"):
            with self.subTest(helper=name):
                self._assert_same_source(name, self.guard, self.node, self.uv)

    def test_enforcers_deny_malformed_tool_args(self) -> None:
        scripts = (
            SCRIPTS_DIR / "executable_copilot-guard.py",
            SCRIPTS_DIR / "executable_node-global-enforcer.py",
            SCRIPTS_DIR / "executable_uv-enforcer.py",
        )
        cases = (
            ("invalid-json-string", "not-json"),
            ("json-list-string", "[]"),
            ("list", []),
            ("scalar", 42),
        )
        for script in scripts:
            for case, tool_args in cases:
                with self.subTest(script=script.name, case=case):
                    result = run_hook(
                        script,
                        {"toolName": "bash", "toolArgs": tool_args},
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    decision = json.loads(result.stdout)
                    self.assertEqual(decision["permissionDecision"], "deny")

    def test_command_parsing_identical(self) -> None:
        self._assert_same_source("split_command_chain", self.node, self.uv)
        self.assertEqual(self.node._PREFIX_ARG_FLAGS, self.uv._PREFIX_ARG_FLAGS)

    def test_audit_helpers_identical(self) -> None:
        for name in ("redact", "rotate_if_needed", "_parse_tool_args"):
            with self.subTest(helper=name):
                self._assert_same_source(name, self.audit_log, self.audit_failure)

    def test_audit_rotation_threshold_identical(self) -> None:
        self.assertEqual(self.audit_log.MAX_LOG_BYTES, self.audit_failure.MAX_LOG_BYTES)


if __name__ == "__main__":
    unittest.main()
