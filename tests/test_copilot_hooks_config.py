"""Verify Copilot hooks launch a pinned interpreter on every shell."""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests._helpers import run_hook

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "home/private_dot_copilot/hooks"
HOOKS_PATH = HOOKS_DIR / "hooks.json"
POSIX_LAUNCHER = HOOKS_DIR / "executable_run-hook.sh"
WINDOWS_LAUNCHER = HOOKS_DIR / "run-hook.ps1"
POSIX_PROVISIONER = REPO_ROOT / "home/run_after_25-provision-copilot-hook-python.sh.tmpl"
WINDOWS_PROVISIONER = REPO_ROOT / "home/run_after_25-provision-copilot-hook-python.ps1.tmpl"


class CopilotHooksConfigTests(unittest.TestCase):
    def test_provisioners_use_the_distributed_hook_directory(self) -> None:
        posix = POSIX_PROVISIONER.read_text(encoding="utf-8")
        windows = WINDOWS_PROVISIONER.read_text(encoding="utf-8")

        self.assertIn('hooks_dir="${HOME}/.copilot/hooks"', posix)
        self.assertNotIn("COPILOT_HOME", posix)
        self.assertIn("$hooksDir = Join-Path $HOME '.copilot\\hooks'", windows)
        self.assertNotIn("COPILOT_HOME", windows)

    def test_guard_chain_checks_original_command_before_rewriting(self) -> None:
        scripts = REPO_ROOT / "home/private_dot_copilot/hooks/scripts"
        for command, denying_script in (("python script.py", "uv-enforcer.py"),):
            with self.subTest(command=command):
                args = {"command": command}
                seen = []
                for name in ("copilot-guard.py", "uv-enforcer.py"):
                    seen.append(args["command"])
                    result = run_hook(scripts / f"executable_{name}", {"toolName": "bash", "toolArgs": args})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    output = json.loads(result.stdout) if result.stdout.strip() else {}
                    if output.get("permissionDecision") == "deny":
                        self.assertEqual(name, denying_script)
                        break
                    args = output.get("modifiedArgs", args)
                else:
                    self.fail("guard chain did not deny the command")
                self.assertTrue(all(value == command for value in seen))

    def test_registered_hooks_do_not_block_global_node_install(self) -> None:
        hooks = json.loads(HOOKS_PATH.read_text())["hooks"]["preToolUse"]
        scripts = REPO_ROOT / "home/private_dot_copilot/hooks/scripts"
        args = {"command": "npm install --global example"}

        for hook in hooks:
            name = hook["bash"].rsplit(" ", maxsplit=1)[-1]
            with self.subTest(hook=name):
                result = run_hook(
                    scripts / f"executable_{name}",
                    {"toolName": "bash", "toolArgs": args},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout) if result.stdout.strip() else {}
                self.assertNotEqual(output.get("permissionDecision"), "deny")


class CopilotHookLauncherTests(unittest.TestCase):
    """Launcher は記録済み interpreter だけを、検証したうえで実行する。"""

    def _install_launcher(self, root: pathlib.Path) -> pathlib.Path:
        hooks_dir = root / "hooks"
        (hooks_dir / "scripts").mkdir(parents=True)
        launcher = hooks_dir / "run-hook.sh"
        launcher.write_text(POSIX_LAUNCHER.read_text(encoding="utf-8"), encoding="utf-8")
        launcher.chmod(0o755)
        (hooks_dir / "scripts" / "probe.py").write_text(
            "import sys\n"
            "sys.stdout.write(sys.stdin.read().strip() + '|' + sys.executable)\n",
            encoding="utf-8",
        )
        return launcher

    def _write_runtime(
        self, launcher: pathlib.Path, python_root: str, python_path: str
    ) -> None:
        (launcher.parent / "python-runtime.env").write_text(
            f"python_root={python_root}\npython={python_path}\n", encoding="utf-8"
        )

    def _run(self, launcher: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(launcher), *args],
            check=False,
            capture_output=True,
            text=True,
            input="payload",
        )

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    @unittest.skipIf(os.name == "nt", "the POSIX launcher requires a POSIX shell")
    def test_launcher_runs_the_recorded_interpreter_with_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launcher = self._install_launcher(pathlib.Path(temp_dir))
            interpreter = pathlib.Path(sys.executable).resolve()
            self._write_runtime(launcher, str(interpreter.parent), str(interpreter))

            result = self._run(launcher, "probe.py")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, f"payload|{interpreter}")

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    @unittest.skipIf(os.name == "nt", "the POSIX launcher requires a POSIX shell")
    def test_launcher_rejects_unusable_runtime_records(self) -> None:
        interpreter = pathlib.Path(sys.executable).resolve()
        cases = {
            "missing-record": None,
            "outside-root": (str(interpreter.parent / "nested"), str(interpreter)),
            "relative-root": ("relative/root", str(interpreter)),
            "absent-interpreter": (
                str(interpreter.parent),
                str(interpreter.parent / "absent-interpreter"),
            ),
        }
        for name, record in cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temp_dir:
                launcher = self._install_launcher(pathlib.Path(temp_dir))
                if record is not None:
                    self._write_runtime(launcher, *record)

                result = self._run(launcher, "probe.py")

                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("copilot hook launcher", result.stderr)

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    @unittest.skipIf(os.name == "nt", "the POSIX launcher requires a POSIX shell")
    def test_launcher_rejects_script_names_that_escape_the_scripts_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launcher = self._install_launcher(pathlib.Path(temp_dir))
            interpreter = pathlib.Path(sys.executable).resolve()
            self._write_runtime(launcher, str(interpreter.parent), str(interpreter))

            for script_name in ("../probe.py", "sub/probe.py", "..\\probe.py"):
                with self.subTest(script_name=script_name):
                    result = self._run(launcher, script_name)

                    self.assertEqual(result.returncode, 1, result.stdout)
                    self.assertIn("bare file name", result.stderr)

    def test_both_launchers_are_distributed(self) -> None:
        self.assertTrue(POSIX_LAUNCHER.is_file())
        self.assertTrue(WINDOWS_LAUNCHER.is_file())
        for launcher in (POSIX_LAUNCHER, WINDOWS_LAUNCHER):
            with self.subTest(launcher=launcher.name):
                source = launcher.read_text(encoding="utf-8")
                self.assertIn("python-runtime.env", source)
                self.assertNotIn("uv run", source)

    def test_windows_launcher_forwards_all_pipeline_input_to_python(self) -> None:
        source = WINDOWS_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("[Parameter(ValueFromPipeline = $true)]", source)
        self.assertIn("[object] $HookInput", source)
        self.assertIn("begin {", source)
        self.assertIn("process {", source)
        self.assertIn("end {", source)
        self.assertIn("$hookInputs.Add($HookInput)", source)
        self.assertNotIn("@($input)", source)
        self.assertIn(
            "$hookInputs | & $pythonPath $scriptPath @HookArguments",
            source,
        )

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_windows_launcher_preserves_pipeline_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            hooks_dir = pathlib.Path(temp_dir) / "hooks"
            scripts_dir = hooks_dir / "scripts"
            scripts_dir.mkdir(parents=True)
            launcher = hooks_dir / "run-hook.ps1"
            launcher.write_text(
                WINDOWS_LAUNCHER.read_text(encoding="utf-8"), encoding="utf-8"
            )
            (scripts_dir / "probe.py").write_text(
                "import json, sys\n"
                "sys.stdout.write(json.dumps(sys.stdin.read()))\n",
                encoding="utf-8",
            )
            interpreter = pathlib.Path(sys.executable).resolve()
            self._write_runtime(
                launcher, str(interpreter.parent), str(interpreter)
            )

            cases = {
                "single": (
                    f"'first' | & '{launcher}' probe.py",
                    ("first",),
                ),
                "multiple": (
                    f"@('first', 'second') | & '{launcher}' probe.py",
                    ("first", "second"),
                ),
                "empty": (f"& '{launcher}' probe.py", ()),
            }
            for name, (command, expected) in cases.items():
                with self.subTest(case=name):
                    result = subprocess.run(
                        [
                            "pwsh",
                            "-NoProfile",
                            "-NonInteractive",
                            "-Command",
                            command,
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )

                    self.assertEqual(result.returncode, 0, result.stderr)
                    forwarded = json.loads(result.stdout)
                    if expected:
                        positions = [forwarded.index(value) for value in expected]
                        self.assertEqual(positions, sorted(positions))
                    else:
                        self.assertEqual(forwarded, "")
