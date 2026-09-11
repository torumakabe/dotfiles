# /// script
# requires-python = ">=3.13"
# ///
"""uv Enforcer — preToolUse hook for uv execution in Copilot shell tools.

Ensures all Python operations go through uv (uv run, uv add, uv pip).
Allowed shell commands are updated to use a Copilot-owned writable uv cache.

Run via: uv run uv-enforcer.py
"""
from __future__ import annotations

import json
import ntpath
import os
import posixpath
import re
import shlex
import sys
from collections.abc import Mapping
from typing import Any


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def deny(reason: str) -> None:
    print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": reason}))
    sys.exit(0)


def emit_modified_args(tool_args: dict[str, Any]) -> None:
    print(json.dumps({"modifiedArgs": tool_args}))


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


def copilot_uv_cache_dir(
    platform_name: str = sys.platform,
    environ: Mapping[str, str] = os.environ,
    home: str | None = None,
) -> str:
    """Return the Copilot-owned uv cache path used by sandbox shell commands."""
    resolved_home = home or str(os.path.expanduser("~"))
    if platform_name == "win32":
        cache_home = environ.get("LOCALAPPDATA") or ntpath.join(
            resolved_home, "AppData", "Local"
        )
        return ntpath.join(cache_home, "GitHubCopilot", "uv")
    if platform_name == "darwin":
        return posixpath.join(resolved_home, "Library", "Caches", "github-copilot", "uv")
    cache_home = environ.get("XDG_CACHE_HOME") or posixpath.join(
        resolved_home, ".cache"
    )
    return posixpath.join(cache_home, "github-copilot", "uv")


def with_copilot_uv_cache(
    tool_name: str,
    tool_args: dict[str, Any],
    cache_dir: str | None = None,
) -> dict[str, Any] | None:
    """Apply ADR-030 without exposing the cache path to runtime discovery."""
    command = tool_args.get("command")
    if tool_name not in ("bash", "powershell") or not isinstance(command, str) or not command:
        return None

    cache_dir = cache_dir or copilot_uv_cache_dir()
    modified = dict(tool_args)
    if tool_name == "powershell":
        escaped = cache_dir.replace("'", "''")
        modified["command"] = (
            f"$env:UV_CACHE_DIR = '{escaped}'; & {{\n{command}\n}}"
        )
    else:
        modified["command"] = (
            f"export UV_CACHE_DIR={shlex.quote(cache_dir)};\n{command}"
        )
    return modified


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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

    modified_args = with_copilot_uv_cache(tool_name, tool_args)
    if modified_args is not None:
        emit_modified_args(modified_args)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        deny("Hook script error - fail-safe deny")
