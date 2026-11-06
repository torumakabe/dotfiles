"""Shared helpers for the test suite.

Always import these as `from tests._helpers import ...` so both unittest
discovery and individual test modules use the same helpers.
"""
from __future__ import annotations

import contextlib
import ctypes
import os
import sys
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
