"""Verify shared test helpers preserve process state."""

import ctypes
import os
import subprocess
import sys
import unittest

from tests._helpers import scoped_environ


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class ScopedEnvironTests(unittest.TestCase):
    def test_restores_empty_value_for_native_child_process(self) -> None:
        name = "COPILOT_SCOPED_ENVIRON_EMPTY_TEST"
        environment = getattr(os, "environ")
        environment[name] = ""
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        set_environment_variable = kernel32.SetEnvironmentVariableW
        set_environment_variable.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        set_environment_variable.restype = ctypes.c_int
        self.assertTrue(set_environment_variable(name, ""))
        self.addCleanup(environment.pop, name, None)

        with scoped_environ({name: "temporary"}):
            self.assertEqual(environment[name], "temporary")

        self.assertEqual(environment[name], "")
        result = subprocess.run(
            [
                "pwsh",
                "-NoLogo",
                "-NoProfile",
                "-Command",
                (
                    f"$value = [Environment]::GetEnvironmentVariable('{name}', 'Process'); "
                    "if ($null -eq $value) { 'missing' } else { 'present:' + $value.Length }"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "present:0")


if __name__ == "__main__":
    unittest.main()
