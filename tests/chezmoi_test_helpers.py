"""Shared helpers for rendering chezmoi templates in tests."""

from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile


def execute_template(
    path: pathlib.Path,
    data: dict,
    source_root: pathlib.Path,
) -> subprocess.CompletedProcess[str]:
    """Render a template with override data passed through a temporary file."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        data_path = pathlib.Path(temporary_directory) / "data.json"
        data_path.write_text(
            json.dumps(data, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return subprocess.run(
            [
                "chezmoi",
                "execute-template",
                "--source",
                str(source_root),
                "--override-data-file",
                str(data_path),
                "--file",
                str(path),
            ],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
