# /// script
# requires-python = ">=3.13"
# ///
"""uv Enforcer — preToolUse hook that blocks direct python/pip execution.

Ensures all Python operations go through uv (uv run, uv add, uv pip).
Reads a JSON tool-call from stdin and emits a JSON permission decision on stdout.

Run via: uv run uv-enforcer.py
"""
from __future__ import annotations

import json
import ntpath
import os
from pathlib import Path
from pathlib import PureWindowsPath
import re
import shlex
import stat
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def deny(reason: str) -> None:
    print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": reason}))
    sys.exit(0)


# ---------------------------------------------------------------------------
# Input handling (absorb Windows encoding differences)
# ---------------------------------------------------------------------------

def read_input() -> dict:
    """Read and parse JSON from stdin, handling Windows BOM/encoding."""
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

    raw = sys.stdin.read().strip()
    raw = raw.lstrip("\ufeff\ufffe")
    return json.loads(raw)


def parse_tool_args(raw: Any) -> dict[str, Any]:
    """Normalize toolArgs from the hook input.

    toolArgs may arrive as a JSON object or as a string containing one.
    Invalid JSON and non-object values raise so main() emits a fail-safe deny.
    """
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise TypeError("toolArgs must be a JSON object")
    return raw


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------

def split_command_chain(command: str) -> list[str]:
    """Split a command string by shell operators (&&, ||, ;).

    Returns individual command segments with leading/trailing whitespace stripped.
    Pipe (|) chains are treated as a single segment led by the first command,
    because blocking only the piped-to portion would be confusing.
    """
    # Split by && || ; but NOT by single |
    # We want "echo foo | python" to be caught as a whole, but
    # "cmd1 && python script.py" to be split into ["cmd1", "python script.py"]
    segments = re.split(r"\s*(?:&&|\|\||;)\s*", command)
    return [s.strip() for s in segments if s.strip()]


_PREFIX_COMMANDS = frozenset({"sudo", "env", "command"})

# Flags of prefix commands that consume the next token as their argument
# (e.g. sudo -u root, sudo -g wheel, env -u VAR)
_PREFIX_ARG_FLAGS = frozenset({"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"})


def extract_leading_command(segment: str) -> str:
    """Extract the command name from the beginning of a shell segment.

    Skips leading environment variable assignments (FOO=bar), prefix
    commands (sudo, env), their flags (including flag arguments), and
    strips absolute paths.
    """
    tokens = segment.split()
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if "=" in token and not token.startswith("="):
            continue
        if "/" in token:
            token = token.rsplit("/", 1)[-1]
        if token in _PREFIX_COMMANDS:
            continue
        if token.startswith("-"):
            if token in _PREFIX_ARG_FLAGS:
                skip_next = True
            continue
        return token
    return ""


# ---------------------------------------------------------------------------
# Block rules
# ---------------------------------------------------------------------------

# Blocked executable names at command position
BLOCKED_COMMANDS: dict[str, str] = {
    "python": "Use 'uv run python' instead of 'python'. Example: uv run python script.py",
    "python3": "Use 'uv run python' instead of 'python3'. Example: uv run python script.py",
    "pip": "Use 'uv add' to install packages, or 'uv pip' for other pip operations",
    "pip3": "Use 'uv add' to install packages, or 'uv pip' for other pip operations",
}

VERSIONED_PYTHON_RE = re.compile(r"^python3(?:\.\d+)+(?:\.exe)?$")
VERSIONED_PIP_RE = re.compile(r"^pip3(?:\.\d+)+(?:\.exe)?$")


def blocked_command_reason(command_name: str) -> str | None:
    """Return the deny reason for blocked Python executables."""
    normalized = command_name.lower()
    if normalized.endswith(".exe"):
        normalized = normalized[:-4]
    if normalized in BLOCKED_COMMANDS:
        return BLOCKED_COMMANDS[normalized]
    if VERSIONED_PYTHON_RE.match(command_name.lower()):
        return "Use 'uv run python' instead of versioned Python executables. Example: uv run python script.py"
    if VERSIONED_PIP_RE.match(command_name.lower()):
        return "Use 'uv add' to install packages, or 'uv pip' for other pip operations"
    return None


def check_command(command: str) -> str | None:
    """Check if a command string contains blocked Python invocations.

    Returns a deny reason if blocked, None if allowed.
    """
    stripped = command.strip()

    for segment in split_command_chain(stripped):
        # Skip segments led by uv
        if segment.startswith("uv ") or segment == "uv":
            continue

        lead = extract_leading_command(segment)
        reason = blocked_command_reason(lead)
        if reason:
            return reason

        # Also check right-hand side of pipes: "echo foo | python script.py"
        pipe_parts = segment.split("|")
        for part in pipe_parts[1:]:
            piped_lead = extract_leading_command(part.strip())
            reason = blocked_command_reason(piped_lead)
            if reason:
                return reason

    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def copilot_uv_cache_dir() -> str:
    """Return the dedicated POSIX cache, rejecting redirected or unsafe paths."""
    if "UV_CACHE_DIR" in os.environ:
        raise ValueError("Unset launch-environment UV_CACHE_DIR before applying settings and starting Copilot; command-local overrides remain supported.")
    home_value = os.environ.get("HOME", "")
    home = Path(home_value)
    if not home.is_absolute() or any(c in home_value for c in "\r\n"):
        raise ValueError("HOME must be an absolute, single-line directory.")
    if "//" in home_value or str(home) != home_value.rstrip("/") or ".." in home.parts:
        raise ValueError("HOME must not contain redundant separators or '.'/'..' components.")
    home = home.resolve(strict=True)
    if home == Path("/") or not home.is_dir() or any(c in str(home) for c in "\r\n"):
        raise ValueError("HOME must resolve to a non-root, single-line directory.")
    base_value = (
        str(home / "Library/Caches")
        if sys.platform == "darwin"
        else os.environ.get("XDG_CACHE_HOME") or str(home / ".cache")
    )
    if (
        not base_value.startswith("/")
        or any(c in base_value for c in "\r\n")
        or ".." in base_value.split("/")
    ):
        raise ValueError("XDG_CACHE_HOME must be absolute, single-line, and contain no '..' components.")
    base = Path("/" + base_value.lstrip("/"))
    # HOME itself may be an OS alias; reject redirects below it and in external XDG paths.
    if base.is_relative_to(Path(home_value)):
        base = home / base.relative_to(Path(home_value))
    if base == Path("/"):
        raise ValueError("XDG_CACHE_HOME must not be the filesystem root.")
    cache = base / "github-copilot/uv"
    for component in reversed((cache, *cache.parents)):
        if component.is_symlink() or (component.exists() and not component.is_dir()):
            raise ValueError(f"Cache path must not contain symlinks or non-directories: {component}")
    return str(cache)


def _has_reparse_point(path: Path) -> bool:
    try:
        file_attributes = os.lstat(path).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(file_attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _check_existing_windows_components(path: PureWindowsPath, label: str) -> None:
    current = Path(path.anchor)
    if _has_reparse_point(current):
        raise ValueError(f"{label} must not contain symlinks or reparse points: {current}")
    if current.exists() and not current.is_dir():
        raise ValueError(f"{label} must not contain non-directories: {current}")
    for component in path.parts[1:]:
        current = current / component
        if not current.exists():
            continue
        if _has_reparse_point(current):
            raise ValueError(f"{label} must not contain symlinks or reparse points: {current}")
        if not current.is_dir():
            raise ValueError(f"{label} must not contain non-directories: {current}")


def copilot_uv_cache_dir_windows() -> str:
    """Return the dedicated Windows cache, rejecting redirected or unsafe paths."""
    if "UV_CACHE_DIR" in os.environ:
        raise ValueError("Unset launch-environment UV_CACHE_DIR before applying settings and starting Copilot; command-local overrides remain supported.")
    local_app_data_value = os.environ.get("LOCALAPPDATA", "")
    local_app_data = PureWindowsPath(local_app_data_value)
    if (
        not local_app_data_value
        or any(c in local_app_data_value for c in "\r\n")
        or not local_app_data.is_absolute()
        or not local_app_data.drive
        or local_app_data_value.startswith(("\\\\", "//"))
        or local_app_data.drive.startswith("\\\\")
    ):
        raise ValueError("LOCALAPPDATA must be a local absolute, single-line directory.")
    suffix = local_app_data_value[len(local_app_data.anchor):]
    if (
        re.search(r"[\\/]{2,}", suffix)
        or re.search(r"(^|[\\/])\.(?:[\\/]|$)", suffix)
        or re.search(r"(^|[\\/])\.\.(?:[\\/]|$)", suffix)
    ):
        raise ValueError("LOCALAPPDATA must not contain redundant separators or '.'/'..' components.")
    _check_existing_windows_components(local_app_data, "LOCALAPPDATA")
    resolved_local_app_data = Path(local_app_data_value).resolve(strict=True)
    if (
        not resolved_local_app_data.is_dir()
        or any(c in str(resolved_local_app_data) for c in "\r\n")
    ):
        raise ValueError("LOCALAPPDATA must resolve to a non-root, single-line directory.")
    drive_root = Path(ntpath.splitdrive(str(resolved_local_app_data))[0] + "\\")
    if resolved_local_app_data == drive_root:
        raise ValueError("LOCALAPPDATA must not resolve to a drive root.")
    cache = resolved_local_app_data / "github-copilot" / "uv"
    for component in reversed((cache, *cache.parents)):
        if _has_reparse_point(component):
            raise ValueError(f"Cache path must not contain symlinks or reparse points: {component}")
        if component.exists() and not component.is_dir():
            raise ValueError(f"Cache path must not contain symlinks or non-directories: {component}")
    return str(cache)


def main() -> None:
    try:
        input_data = read_input()
    except Exception:
        deny("Failed to parse input - fail-safe deny")

    tool_name: str = input_data.get("toolName", "")

    # Only bash / powershell commands
    if tool_name not in ("bash", "powershell"):
        return  # Not our concern — defer to CLI default

    tool_args = parse_tool_args(input_data.get("toolArgs", {}))

    command: str = tool_args.get("command", "")
    if not command:
        return  # Nothing to check — defer to CLI default

    reason = check_command(command)
    if reason:
        deny(reason)

    if tool_name == "bash" and sys.platform != "win32":
        try:
            cache_dir = copilot_uv_cache_dir()
        except (ValueError, OSError) as exc:
            deny(str(exc))
        # Command-local only: launch-time UV_CACHE_DIR causes ROOT_RO conflicts.
        # Scope/removal conditions: repository .github/copilot-instructions.md workarounds.
        prefix = f"export UV_CACHE_DIR={shlex.quote(cache_dir)}; "
        if not command.startswith(prefix):
            print(json.dumps({"modifiedArgs": {**tool_args, "command": prefix + command}}))
    elif tool_name == "powershell" and sys.platform == "win32":
        try:
            cache_dir = copilot_uv_cache_dir_windows()
        except (ValueError, OSError) as exc:
            deny(str(exc))
        # Command-local only: launch-time UV_CACHE_DIR follows the sandboxed
        # LOCALAPPDATA redirect, so set the host cache path per command instead.
        escaped_cache_dir = cache_dir.replace("'", "''")
        prefix = f"$env:UV_CACHE_DIR = '{escaped_cache_dir}'; "
        if not command.startswith(prefix):
            print(json.dumps({"modifiedArgs": {**tool_args, "command": prefix + command}}))

    return  # Command is fine — defer to CLI default


if __name__ == "__main__":
    try:
        main()
    except Exception:
        deny("Hook script error - fail-safe deny")
