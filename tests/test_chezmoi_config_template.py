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

import os
import pathlib
import shutil
import subprocess
import tempfile
import tomllib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_TEMPLATE_PATH = REPO_ROOT / "home/.chezmoi.toml.tmpl"

# ``windowsUser`` only reaches ``promptStringOnce`` under WSL with interop, and
# on Windows it comes from ``USERNAME``. Everywhere else the seed alone decides
# its value, so the two variables share the seed but not the prompt condition.
PROMPTED_VARIABLES = ("windowsUser", "corpUser")

EXPECTED_PS1_INTERPRETER = {"command": "pwsh", "args": ["-NoLogo", "-NoProfile", "-File"]}


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi renders the config template")
class ConfigTemplateBehaviourTests(unittest.TestCase):
    """Render the real template the way ``chezmoi init`` does.

    ``execute-template --init`` with ``--config`` reproduces a re-init against
    an existing config. ``--stdinisatty`` has to be passed explicitly: the flag
    defaults to ``true`` regardless of the test process's real stdin, so
    omitting it would exercise the interactive path and leave the
    non-interactive case -- the one that used to wipe the answers -- unchecked.
    """

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.template = CONFIG_TEMPLATE_PATH.read_text(encoding="utf-8")

    def _render(
        self,
        existing: str | None,
        *,
        stdin_is_atty: bool,
        environment: dict[str, str] | None = None,
    ) -> str:
        config = self.root / "config.toml"
        if existing is not None:
            config.write_text(existing, encoding="utf-8")
        env = dict(os.environ)
        for name in ("CODESPACES", "REMOTE_CONTAINERS"):
            env.pop(name, None)
        if environment is not None:
            env.update(environment)
        return subprocess.run(
            [
                "chezmoi",
                "--config",
                str(config),
                "execute-template",
                "--init",
                f"--stdinisatty={str(stdin_is_atty).lower()}",
            ],
            input=self.template,
            capture_output=True,
            text=True,
            env=env,
            check=True,
        ).stdout

    def _seeded(self, name: str) -> str:
        return f'[data]\n  {name} = "stored-{name}"\n'

    def _prompted_variables(self) -> tuple[str, ...]:
        # On Windows the template takes windowsUser from the USERNAME
        # environment variable instead of the seed, so the stored answer is not
        # the value under test there.
        if os.name == "nt":
            return tuple(name for name in PROMPTED_VARIABLES if name != "windowsUser")
        return PROMPTED_VARIABLES

    def test_reinit_without_a_tty_keeps_the_stored_answers(self) -> None:
        """The regression: the TTY guard must fall back to the stored answers."""
        for name in self._prompted_variables():
            with self.subTest(variable=name):
                rendered = self._render(self._seeded(name), stdin_is_atty=False)
                self.assertIn(f'{name} = "stored-{name}"', rendered)

    def test_reinit_with_a_tty_keeps_the_stored_answers(self) -> None:
        """A TTY must not overwrite the stored answers either.

        ``corpUser`` reaches ``promptStringOnce``, which returns the stored
        answer instead of prompting. ``windowsUser`` reaches it only under WSL,
        so on other hosts this pins the seed against a TTY-only regression.
        """
        for name in self._prompted_variables():
            with self.subTest(variable=name):
                rendered = self._render(self._seeded(name), stdin_is_atty=True)
                self.assertIn(f'{name} = "stored-{name}"', rendered)

    def test_fresh_init_without_a_tty_leaves_the_answers_empty(self) -> None:
        rendered = self._render(None, stdin_is_atty=False)
        for name in self._prompted_variables():
            with self.subTest(variable=name):
                self.assertIn(f'{name} = ""', rendered)

    def test_ps1_interpreter_skips_the_profile(self) -> None:
        """A rendered config must run .ps1 scripts without the PowerShell profile."""
        rendered = self._render(None, stdin_is_atty=False)
        config = tomllib.loads(rendered)
        self.assertEqual(config["interpreters"]["ps1"], EXPECTED_PS1_INTERPRETER)

    def test_container_environment_detection(self) -> None:
        cases = (
            ("ordinary", {}, False, False),
            ("codespaces", {"CODESPACES": "true"}, True, False),
            ("devcontainer", {"REMOTE_CONTAINERS": "true"}, False, True),
        )
        for name, environment, expected_codespaces, expected_devcontainer in cases:
            with self.subTest(environment=name):
                rendered = self._render(
                    None,
                    stdin_is_atty=False,
                    environment=environment,
                )
                data = tomllib.loads(rendered)["data"]
                self.assertIs(data["codespaces"], expected_codespaces)
                self.assertIs(data["devcontainer"], expected_devcontainer)


if __name__ == "__main__":
    unittest.main()
