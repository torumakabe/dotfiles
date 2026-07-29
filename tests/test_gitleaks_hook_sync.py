"""Verify the two gitleaks hook scripts keep an identical scanner block.

ADR-020 deliberately keeps two copies of the gitleaks launcher: the
config-based hook (~/.local/bin/gitleaks-pre-commit) and the
init.templateDir hook (~/.config/git/templates/hooks/pre-commit).
Sharing one file would couple their lifecycles, so ADR-020 chose
duplication and asks for both to be updated together. This test enforces
that rule instead of relying on the author remembering it.
"""
import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_HOOK = REPO_ROOT / "home/dot_local/bin/executable_gitleaks-pre-commit"
TEMPLATE_HOOK = REPO_ROOT / "home/dot_config/git/templates/hooks/executable_pre-commit"

_SHARED_MARKER = "find_gitleaks() {"


def _shared_block(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8")
    index = text.find(_SHARED_MARKER)
    if index < 0:
        raise AssertionError(f"{path} no longer contains {_SHARED_MARKER!r}")
    return text[index:]


class GitleaksHookSyncTests(unittest.TestCase):
    def test_shared_block_identical(self) -> None:
        self.assertEqual(_shared_block(CONFIG_HOOK), _shared_block(TEMPLATE_HOOK))

    def test_both_stay_posix_sh(self) -> None:
        for path in (CONFIG_HOOK, TEMPLATE_HOOK):
            with self.subTest(path=path.name):
                first_line = path.read_text(encoding="utf-8").splitlines()[0]
                self.assertEqual(first_line, "#!/bin/sh")


if __name__ == "__main__":
    unittest.main()
