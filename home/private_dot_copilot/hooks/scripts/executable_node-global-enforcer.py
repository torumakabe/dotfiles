# /// script
# requires-python = ">=3.13"
# ///
"""Node Global Install Enforcer — preToolUse hook that blocks global installs.

Prevents npm/yarn/pnpm/bun from installing packages globally, keeping the
host Node.js environment clean.  One-off execution via npx/bunx/pnpm dlx
and tool management via mise are the intended alternatives.

Reads a JSON tool-call from stdin and emits a JSON permission decision on stdout.

Run via: uv run node-global-enforcer.py
"""
from __future__ import annotations

import json
import re
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

    toolArgs may arrive as a JSON string, a dict, or something else
    entirely.  This function always returns a dict.
    """
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
    return raw if isinstance(raw, dict) else {}


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------

def split_command_chain(command: str) -> list[str]:
    """Split a command string by shell operators (&&, ||, ;).

    Pipe (|) chains are treated as a single segment led by the first command,
    because blocking only the piped-to portion would be confusing.
    """
    segments = re.split(r"\s*(?:&&|\|\||;)\s*", command)
    return [s.strip() for s in segments if s.strip()]


_PREFIX_COMMANDS = frozenset({"sudo", "env", "corepack", "command"})

# Flags of prefix commands that consume the next token as their argument
# (e.g. sudo -u root, sudo -g wheel, env -u VAR)
_PREFIX_ARG_FLAGS = frozenset({"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"})


def tokenize_command(segment: str) -> list[str]:
    """Tokenize a command segment, skipping env vars, prefix commands,
    their flags (including flag arguments), and stripping absolute paths
    from the leading command.
    """
    tokens = segment.split()
    result: list[str] = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if not result and "=" in token and not token.startswith("="):
            continue
        if not result and "/" in token:
            token = token.rsplit("/", 1)[-1]
        if not result and token in _PREFIX_COMMANDS:
            continue
        if not result and token.startswith("-"):
            if token in _PREFIX_ARG_FLAGS:
                skip_next = True
            continue
        result.append(token)
    return result


# ---------------------------------------------------------------------------
# Block rules
# ---------------------------------------------------------------------------

DENY_MESSAGES: dict[str, str] = {
    "npm": (
        "Global npm install is blocked. "
        "Use 'npx <cmd>' for one-off execution, or manage tools with mise."
    ),
    "yarn": (
        "Global yarn install is blocked. "
        "Use 'npx <cmd>' for one-off execution, or manage tools with mise."
    ),
    "pnpm": (
        "Global pnpm install is blocked. "
        "Use 'pnpm dlx <cmd>' or 'npx <cmd>' for one-off execution, "
        "or manage tools with mise."
    ),
    "bun": (
        "Global bun install is blocked. "
        "Use 'bunx <cmd>' for one-off execution, or manage tools with mise."
    ),
    "npm_link": (
        "npm link modifies the global node_modules. "
        "Use 'npx <cmd>' for one-off execution, or manage tools with mise."
    ),
}

_INSTALL_SUBCMDS = frozenset({"install", "i", "add", "link"})


def _has_global_flag(tokens: list[str]) -> bool:
    """Check if any token indicates global installation."""
    for i, t in enumerate(tokens):
        if t == "--":
            return False  # end of flag parsing
        if t in ("-g", "--global", "--location=global"):
            return True
        if t == "--location" and i + 1 < len(tokens) and tokens[i + 1] == "global":
            return True
    return False


def check_segment(segment: str) -> str | None:
    """Check a single command segment for global install patterns.

    Returns a deny reason if blocked, None if allowed.
    """
    tokens = tokenize_command(segment)
    if not tokens:
        return None

    cmd = tokens[0]
    args = tokens[1:]

    if cmd == "npm":
        subcmd = next((t for t in args if not t.startswith("-")), "")
        # npm link/ln always modifies global node_modules (even without -g)
        if subcmd in ("link", "ln"):
            return DENY_MESSAGES["npm_link"]
        if subcmd in ("install", "i", "add") and _has_global_flag(args):
            return DENY_MESSAGES["npm"]

    elif cmd == "yarn":
        # yarn [flags...] global add <pkg>
        try:
            gi = args.index("global")
            if gi + 1 < len(args) and args[gi + 1] == "add":
                return DENY_MESSAGES["yarn"]
        except ValueError:
            pass

    elif cmd == "pnpm":
        if any(t in _INSTALL_SUBCMDS for t in args) and _has_global_flag(args):
            return DENY_MESSAGES["pnpm"]

    elif cmd == "bun":
        if any(t in _INSTALL_SUBCMDS for t in args) and _has_global_flag(args):
            return DENY_MESSAGES["bun"]

    return None


def check_command(command: str) -> str | None:
    """Check if a command string contains blocked global install invocations.

    Returns a deny reason if blocked, None if allowed.
    """
    stripped = command.strip()

    for segment in split_command_chain(stripped):
        pipe_parts = segment.split("|")
        for part in pipe_parts:
            reason = check_segment(part.strip())
            if reason:
                return reason

    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        input_data = read_input()
    except Exception:
        deny("Failed to parse input - fail-safe deny")

    tool_name: str = input_data.get("toolName", "")

    # bash / powershell commands only
    if tool_name not in ("bash", "powershell"):
        return  # Not our concern — defer to CLI default

    tool_args = parse_tool_args(input_data.get("toolArgs", {}))

    command: str = tool_args.get("command", "")
    if not command:
        return  # Nothing to check — defer to CLI default

    reason = check_command(command)
    if reason:
        deny(reason)

    return  # Command is fine — defer to CLI default


if __name__ == "__main__":
    try:
        main()
    except Exception:
        deny("Hook script error - fail-safe deny")
