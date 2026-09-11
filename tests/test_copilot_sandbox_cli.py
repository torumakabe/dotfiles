"""Opt-in real CLI test with normal HOME, Python discovery, and a registered hook.

Run from an ordinary shell with COPILOT_UV_PROBE_PATH="$PATH",
COPILOT_UV_PROBE_VIRTUAL_ENV="${VIRTUAL_ENV-}", and COPILOT_CLI_INTEGRATION=1
before invoking uv run -m unittest tests.test_copilot_sandbox_cli -v.
Only cloned CLI settings are changed. No external model service is used.
"""

import http.server
import importlib.util
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import unittest
import uuid


ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "home/private_dot_copilot/hooks/scripts/executable_uv-enforcer.py"
SYNC = ROOT / "home/run_after_35-configure-copilot-sandbox.sh.tmpl"


@unittest.skipUnless(
    os.environ.get("COPILOT_CLI_INTEGRATION") == "1"
    and os.name != "nt"
    and all(shutil.which(tool) for tool in ("copilot", "uv", "chezmoi", "jq")),
    "opt-in installed POSIX Copilot CLI integration",
)
class CopilotSandboxCliTests(unittest.TestCase):
    def test_normal_home_cache_with_registered_hook(self) -> None:
        home = pathlib.Path.home()
        settings_path = pathlib.Path(
            os.environ.get("COPILOT_HOME", str(home / ".copilot"))
        ) / "settings.json"
        self.assertTrue(settings_path.is_file(), "Normal CLI settings are required")
        self.assertNotIn("UV_CACHE_DIR", os.environ, "Run without a host cache override")
        self.assertTrue(
            os.environ.get("COPILOT_UV_PROBE_PATH"),
            'Set COPILOT_UV_PROBE_PATH="$PATH" before invoking uv run',
        )
        self.assertIn(
            "COPILOT_UV_PROBE_VIRTUAL_ENV", os.environ,
            'Set COPILOT_UV_PROBE_VIRTUAL_ENV="${VIRTUAL_ENV-}" before invoking uv run',
        )
        original_settings = settings_path.read_bytes()
        baseline = json.loads(original_settings)
        spec = importlib.util.spec_from_file_location("uv_cache_hook", HOOK)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)

        # Keep the probe outside the automatically writable OS temporary directory.
        parent = home / ".cache"
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="copilot-uv-probe-", dir=parent) as tmp:
            root = pathlib.Path(tmp).resolve()
            work = root / "work"
            subprocess.run(["git", "init", "--quiet", str(work)], check=True)
            deployed_hook = root / "uv-enforcer.py"
            shutil.copyfile(HOOK, deployed_hook)
            deployed_hook.chmod(0o755)
            config = root / "configured"
            config.mkdir()
            (config / "settings.json").write_bytes(original_settings)
            (config / "settings.json").chmod(0o600)
            chezmoi_config = root / "chezmoi.toml"
            chezmoi_config.write_text("[data]\ncodespaces = false\ndevcontainer = false\n")
            rendered = subprocess.run(
                [
                    "chezmoi", "--source", str(ROOT / "home"),
                    "--config", str(chezmoi_config), "execute-template",
                    "--file", str(SYNC),
                ],
                capture_output=True, text=True, check=True,
            )
            script = root / "configure.sh"
            script.write_text(rendered.stdout)
            env = os.environ.copy()
            # uv run can prepend its selected Python to PATH; do not grant it by accident.
            env["PATH"] = env.pop("COPILOT_UV_PROBE_PATH")
            virtual_env = env.pop("COPILOT_UV_PROBE_VIRTUAL_ENV")
            env.pop("VIRTUAL_ENV", None)
            if virtual_env:
                env["VIRTUAL_ENV"] = virtual_env
            env["COPILOT_HOME"] = str(config)
            configured = subprocess.run(
                ["bash", str(script)], env=env, capture_output=True, text=True,
            )
            self.assertEqual(configured.returncode, 0, configured.stderr)
            policy = json.loads((config / "settings.json").read_text())["sandbox"]
            cache = pathlib.Path(hook.copilot_uv_cache_dir())
            self.assertTrue(cache.is_dir())

            # Retain real tool/config permissions, with no test-only Python grants.
            old_fs = baseline["sandbox"]["userPolicy"]["filesystem"]
            for name in ("readonlyPaths", "deniedPaths"):
                self.assertEqual(policy["userPolicy"]["filesystem"][name], old_fs.get(name, []))
            policy["enabled"] = True
            policy["allowDevToolAccess"] = True
            policy["allowBypass"] = False
            policy["auth"] = {"git": False, "gh": False}

            registrations = json.loads((HOOK.parent.parent / "hooks.json").read_text())
            pre_hooks = [
                registration for registration in registrations["hooks"]["preToolUse"]
                if "uv-enforcer.py" in registration["bash"]
            ]
            self.assertEqual(len(pre_hooks), 1)
            for registration in pre_hooks:
                original_command = registration["bash"]
                resolved, count = re.subn(
                    r'"\$HOME/\.copilot/hooks/scripts/([^"]+)"',
                    lambda match: shlex.quote(str(deployed_hook)),
                    original_command,
                )
                self.assertEqual(count, 1, original_command)
                registration["bash"] = resolved
            marker = cache / ("copilot-probe-" + uuid.uuid4().hex)
            program = (
                "import sys; from pathlib import Path; c = Path(sys.argv[1]); "
                "assert (c / 'CACHEDIR.TAG').is_file(); "
                f"(c / {marker.name!r}).write_text('cache-write-confirmed'); "
                "print('CACHE=' + str(c)); print('PYTHON=' + sys.executable); "
                "print('COPILOT_SANDBOX_UV_OK')"
            )
            command = shlex.join([
                "uv", "--offline", "run", "--no-project",
                "--no-env-file", "--no-python-downloads", "python", "-c", program,
            ]) + ' "$(uv cache dir)"'
            observed = []

            class Provider(http.server.BaseHTTPRequestHandler):
                def log_message(self, *args) -> None:
                    pass

                def do_POST(self) -> None:
                    payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    results = [m for m in payload.get("messages", []) if m.get("role") == "tool"]
                    functions = [t.get("function", {}) for t in payload.get("tools", [])]
                    shell = next(
                        (f for f in functions if f.get("name") in ("bash", "shell")), None,
                    )
                    if results:
                        observed.extend(results)
                        delta, finish = {"content": "Probe finished."}, "stop"
                    elif shell:
                        delta = {"tool_calls": [{
                            "index": 0, "id": "call_uv_probe", "type": "function",
                            "function": {
                                "name": shell["name"],
                                "arguments": json.dumps({
                                    "command": command,
                                    "description": "Verify uv cache persistence",
                                    "initial_wait": 30,
                                }),
                            },
                        }]}
                        finish = "tool_calls"
                    else:
                        observed.append({"error": "No shell tool", "functions": functions})
                        delta, finish = {"content": "Missing shell tool."}, "stop"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for update, reason in ((delta, None), ({}, finish)):
                        chunk = {
                            "id": "probe", "object": "chat.completion.chunk",
                            "created": 0, "model": "sandbox-probe",
                            "choices": [{"index": 0, "delta": update, "finish_reason": reason}],
                        }
                        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")

            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Provider)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for allow_cache in (False, True):
                    with self.subTest(allow_cache=allow_cache):
                        cli_home = root / ("after" if allow_cache else "before")
                        cli_home.mkdir()
                        (cli_home / "config.json").write_text(json.dumps({
                            "hooks": {"preToolUse": pre_hooks},
                        }))
                        this_policy = json.loads(json.dumps(policy))
                        if not allow_cache:
                            grants = this_policy["userPolicy"]["filesystem"]["readwritePaths"]
                            this_policy["userPolicy"]["filesystem"]["readwritePaths"] = [
                                path for path in grants
                                if not cache.is_relative_to(pathlib.Path(path).expanduser())
                            ]
                        (cli_home / "settings.json").write_text(
                            json.dumps({"experimental": True, "sandbox": this_policy})
                        )
                        (cli_home / "settings.json").chmod(0o600)
                        cli_env = env.copy()
                        cli_env.update(
                            COPILOT_HOME=str(cli_home), COPILOT_OFFLINE="true",
                            COPILOT_PROVIDER_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1",
                            COPILOT_PROVIDER_TYPE="openai",
                            COPILOT_PROVIDER_WIRE_API="completions",
                            COPILOT_MODEL="sandbox-probe",
                        )
                        observed.clear()
                        self.assertFalse(marker.exists())
                        result = subprocess.run(
                            [
                                "copilot", "-C", str(work), "--no-auto-update", "--no-remote",
                                "--no-remote-export", "--no-custom-instructions",
                                "--disable-builtin-mcps", "--available-tools=bash",
                                "--allow-all-tools", "--allow-all-paths", "--no-ask-user",
                                "--no-color", "--experimental", "--log-level", "all",
                                "--log-dir", str(root / "logs"),
                                "-p", "Run the single probe.",
                            ],
                            env=cli_env, capture_output=True, text=True, timeout=120,
                        )
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertTrue(observed, result.stdout + result.stderr)
                        evidence = json.dumps(observed)
                        if "hook exited with code 2" in evidence:
                            log_text = "\n".join(
                                path.read_text(errors="replace")
                                for path in (root / "logs").glob("**/*")
                                if path.is_file()
                            )
                            self.fail(
                                evidence + "\nHOOK LOGS:\n"
                                + "\n".join(
                                    line for line in log_text.splitlines()
                                    if "hook" in line.lower() or "uv-enforcer" in line
                                )[-12000:]
                            )
                        print(f"\nNORMAL_HOME grant={allow_cache}: {evidence}", flush=True)
                        if allow_cache:
                            self.assertIn("COPILOT_SANDBOX_UV_OK", evidence)
                            self.assertIn("exit code 0", evidence)
                            self.assertEqual(marker.read_text(), "cache-write-confirmed")
                            self.assertTrue((cache / "CACHEDIR.TAG").is_file())
                        else:
                            self.assertFalse(marker.exists(), "Ungranted cache write persisted")
                            if "COPILOT_SANDBOX_UV_OK" not in evidence:
                                self.assertRegex(evidence.lower(), "permission|denied|not permitted|read-only")
            finally:
                server.shutdown()
                thread.join()
                server.server_close()
                marker.unlink(missing_ok=True)
                self.assertEqual(settings_path.read_bytes(), original_settings)


if __name__ == "__main__":
    unittest.main()
