"""Shared helpers for the test suite.

Always import these as `from tests._helpers import ...`. A bare
`import _helpers` resolves only under `unittest discover -s tests`; the
dotted form additionally keeps `uv run -m unittest tests.test_copilot_guard`
working, which docs/copilot-cli.md and docs/operations.md document.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
from types import ModuleType


def load_script(module_name: str, path: pathlib.Path) -> ModuleType:
    """Import a hook script as a module.

    The hook scripts are standalone `uv run` scripts (ADR-007), so they
    live outside any package and have to be loaded by path.
    """
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_hook(script_path: pathlib.Path, payload: dict | str) -> subprocess.CompletedProcess[str]:
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
    )
