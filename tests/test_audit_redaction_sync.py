"""Verify the three audit-redaction regexes stay identical across scripts.

All three scripts keep a local copy of the redaction regex (self-contained
per ADR style). This test guards against drift: if any of them change
without the others, CI fails.
"""
import pathlib
import unittest

from tests._helpers import load_script


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "home/private_dot_copilot/hooks/scripts"


class RedactionSyncTests(unittest.TestCase):
    """Ensure audit-log.py, audit-failure.py, and copilot-guard.py share regex."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.audit_log = load_script("audit_log", SCRIPTS_DIR / "executable_audit-log.py")
        cls.audit_failure = load_script(
            "audit_failure", SCRIPTS_DIR / "executable_audit-failure.py"
        )
        cls.copilot_guard = load_script(
            "copilot_guard", SCRIPTS_DIR / "executable_copilot-guard.py"
        )

    def test_redaction_patterns_identical(self) -> None:
        log_pattern = self.audit_log._REDACT_PATTERNS.pattern
        fail_pattern = self.audit_failure._REDACT_PATTERNS.pattern
        guard_pattern = self.copilot_guard._AUDIT_REDACT_RE.pattern
        self.assertEqual(log_pattern, fail_pattern)
        self.assertEqual(log_pattern, guard_pattern)

    def test_redaction_flags_identical(self) -> None:
        log_flags = self.audit_log._REDACT_PATTERNS.flags
        fail_flags = self.audit_failure._REDACT_PATTERNS.flags
        guard_flags = self.copilot_guard._AUDIT_REDACT_RE.flags
        self.assertEqual(log_flags, fail_flags)
        self.assertEqual(log_flags, guard_flags)

    def test_redaction_actually_redacts(self) -> None:
        samples = [
            "Authorization: Bearer abc123",
            "token=supersecret",
            "ghp_abcdefghij",
            "sk-abcdefghij1234567890abcdef",
            "AccountKey=AbCd+/=",
        ]
        for sample in samples:
            redacted = self.audit_log.redact(sample)
            self.assertIn("[REDACTED]", redacted, f"Not redacted: {sample}")


if __name__ == "__main__":
    unittest.main()
