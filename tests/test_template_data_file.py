"""Tests for the shared chezmoi template rendering helper."""

from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from tests.chezmoi_test_helpers import execute_template


class ExecuteTemplateTests(unittest.TestCase):
    def test_large_unicode_data_uses_temporary_file_and_small_argv(self) -> None:
        real_run = subprocess.run
        observed_data_path: pathlib.Path | None = None
        observed_argv_length = 0

        with tempfile.TemporaryDirectory() as temporary_directory:
            source_root = pathlib.Path(temporary_directory) / "source with spaces"
            source_root.mkdir()
            template_path = source_root / "template with spaces.tmpl"
            template_path.write_text("{{ .message }}", encoding="utf-8", newline="\n")
            data = {"message": "日本語 " + ("x" * (64 * 1024))}

            def run_and_inspect(
                argv: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                nonlocal observed_data_path, observed_argv_length
                observed_argv_length = sum(len(argument) + 1 for argument in argv)
                data_index = argv.index("--override-data-file") + 1
                observed_data_path = pathlib.Path(argv[data_index])
                self.assertTrue(observed_data_path.is_file())
                self.assertEqual(
                    json.loads(observed_data_path.read_text(encoding="utf-8")),
                    data,
                )
                return real_run(argv, **kwargs)

            with mock.patch(
                "tests.chezmoi_test_helpers.subprocess.run",
                side_effect=run_and_inspect,
            ):
                result = execute_template(template_path, data, source_root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, data["message"])
        self.assertLess(observed_argv_length, 32767)
        self.assertIsNotNone(observed_data_path)
        assert observed_data_path is not None
        self.assertFalse(observed_data_path.exists())


if __name__ == "__main__":
    unittest.main()
