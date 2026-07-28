"""Guard the chezmoi config template against losing prompted values.

``home/.chezmoi.toml.tmpl`` asks for ``windowsUser`` / ``corpUser`` only when
stdin is a TTY. ``promptStringOnce`` would return the stored answer without
prompting, but the TTY guard skips the call entirely, so a non-interactive
``chezmoi init`` (scripts, Codespaces, Dev Container, agent shells) used to
write empty strings over the existing answers. Both values feed git config:
``corpUser`` selects ``gitconfig-corp`` and ``windowsUser`` builds the
ADR-012 op-ssh-sign paths, so losing them breaks commit signing silently.

The fix seeds each variable from the current config data before the guard.
These tests pin both the source shape and the observable behaviour.

The template also pins the ``.ps1`` interpreter (ADR-023). chezmoi defaults to
``pwsh -NoLogo -File``, which loads the profile, which activates mise, whose
CommandNotFound handler dereferences a PSReadLine type that a non-interactive
pwsh does not have. Every failed command lookup inside a script then prints an
InvalidOperation error, so ``-NoProfile`` has to stay in the argument list.
"""

import pathlib
import shutil
import subprocess
import tempfile
import tomllib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_TEMPLATE_PATH = REPO_ROOT / "home/.chezmoi.toml.tmpl"

PROMPTED_VARIABLES = ("windowsUser", "corpUser")

EXPECTED_PS1_INTERPRETER = {"command": "pwsh", "args": ["-NoLogo", "-NoProfile", "-File"]}


class ConfigTemplateSourceTests(unittest.TestCase):
    """Every prompted variable seeds itself from the existing config data."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.template = CONFIG_TEMPLATE_PATH.read_text(encoding="utf-8")

    def test_prompted_variables_seed_from_existing_data(self) -> None:
        for name in PROMPTED_VARIABLES:
            with self.subTest(variable=name):
                self.assertIn(f'{{{{- if hasKey . "{name}" -}}}}', self.template)
                self.assertIn(f"{{{{-   ${name} = .{name} -}}}}", self.template)

    def test_seed_precedes_the_tty_guarded_prompt(self) -> None:
        """The seed is a fallback, so the prompt has to be able to override it."""
        for name in PROMPTED_VARIABLES:
            with self.subTest(variable=name):
                seed = self.template.find(f'{{{{- if hasKey . "{name}" -}}}}')
                prompt = self.template.find(f'promptStringOnce . "{name}"')
                self.assertNotEqual(seed, -1)
                self.assertNotEqual(prompt, -1)
                self.assertLess(seed, prompt)

    def test_ps1_interpreter_is_pinned_without_the_profile(self) -> None:
        """The interpreter is literal TOML, so the source has to carry it verbatim."""
        args = ", ".join(f'"{arg}"' for arg in EXPECTED_PS1_INTERPRETER["args"])
        self.assertIn("[interpreters.ps1]", self.template)
        self.assertIn(f'command = "{EXPECTED_PS1_INTERPRETER["command"]}"', self.template)
        self.assertIn(f"args = [{args}]", self.template)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi renders the config template")
class ConfigTemplateBehaviourTests(unittest.TestCase):
    """Render the real template the way ``chezmoi init`` does.

    ``execute-template --init`` with ``--config`` reproduces a re-init against
    an existing config. The test process has no TTY, which is exactly the case
    that used to wipe the answers.
    """

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.template = CONFIG_TEMPLATE_PATH.read_text(encoding="utf-8")

    def _render(self, existing: str | None) -> str:
        config = self.root / "config.toml"
        if existing is not None:
            config.write_text(existing, encoding="utf-8")
        return subprocess.run(
            ["chezmoi", "--config", str(config), "execute-template", "--init"],
            input=self.template,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def test_reinit_keeps_the_stored_corp_user(self) -> None:
        rendered = self._render('[data]\n  corpUser = "stored-corp"\n')
        self.assertIn('corpUser = "stored-corp"', rendered)

    def test_fresh_init_leaves_the_corp_user_empty(self) -> None:
        rendered = self._render(None)
        self.assertIn('corpUser = ""', rendered)

    def test_ps1_interpreter_skips_the_profile(self) -> None:
        """A rendered config must run .ps1 scripts without the PowerShell profile."""
        rendered = self._render(None)
        config = tomllib.loads(rendered)
        self.assertEqual(config["interpreters"]["ps1"], EXPECTED_PS1_INTERPRETER)


if __name__ == "__main__":
    unittest.main()
