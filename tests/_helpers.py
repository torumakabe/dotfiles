"""Shared helpers for the test suite.

Always import these as `from tests._helpers import ...`. A bare
`import _helpers` resolves only under `unittest discover -s tests`; the
dotted form additionally keeps `uv run -m unittest tests.test_copilot_guard`
working, which docs/copilot-cli.md and docs/operations.md document.
"""
from __future__ import annotations

import contextlib
import ctypes
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
from types import ModuleType
from typing import Iterator, Mapping


def _restore_environment_value(name: str, value: str) -> None:
    os.environ[name] = value
    if sys.platform != "win32" or value != "":
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_environment_variable = kernel32.SetEnvironmentVariableW
    set_environment_variable.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    set_environment_variable.restype = ctypes.c_int
    if not set_environment_variable(name, ""):
        raise ctypes.WinError(ctypes.get_last_error())


@contextlib.contextmanager
def scoped_environ(
    overrides: Mapping[str, str] | None = None,
    *,
    unset: tuple[str, ...] = (),
) -> Iterator[None]:
    """Temporarily modify only the specified environment variables.

    Avoid clearing and restoring the complete environment. On Windows,
    restoring an empty value through ``os.environ`` removes that variable
    from the native process environment and can break later subprocesses.
    """
    overrides = overrides or {}
    sentinel = object()
    touched = set(overrides) | set(unset)
    saved = {name: os.environ.get(name, sentinel) for name in touched}
    try:
        for name in unset:
            os.environ.pop(name, None)
        os.environ.update(overrides)
        yield
    finally:
        for name, value in saved.items():
            if value is sentinel:
                os.environ.pop(name, None)
            else:
                _restore_environment_value(name, value)


def load_script(module_name: str, path: pathlib.Path) -> ModuleType:
    """Import a hook script as a module.

    The hook scripts are standalone `uv run` scripts (ADR-007), so they
    live outside any package and have to be loaded by path.
    """
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
    exec(code, module.__dict__)
    return module


def run_hook(
    script_path: pathlib.Path,
    payload: dict | str,
    *,
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a hook script end to end and return the completed process.

    A dict payload is JSON-encoded; a str payload is sent verbatim so tests
    can feed malformed input. The completed process is returned rather than
    parsed output because an allow decision is an empty stdout, not JSON.
    """
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(script_path)],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
