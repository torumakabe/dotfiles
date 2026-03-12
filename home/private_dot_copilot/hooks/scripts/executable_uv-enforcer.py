# /// script
# requires-python = ">=3.9"
# ///
"""uv Enforcer — preToolUse hook that blocks direct python/pip execution.

Ensures all Python operations go through uv (uv run, uv add, uv pip).
Reads a JSON tool-call from stdin and emits a JSON permission decision on stdout.

Run via: uv run uv-enforcer.py
"""
from __future__ import annotations

import json
import re
import sys


def deny(reason: str) -> None:
    print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": reason}))
    sys.exit(0)


def allow() -> None:
    print(json.dumps({"permissionDecision": "allow"}))
    sys.exit(0)


# ---------------------------------------------------------------------------
# stdin handling (absorb Windows encoding differences)
# ---------------------------------------------------------------------------

def read_input() -> dict:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

    raw = sys.stdin.read().strip()
    raw = raw.lstrip("\ufeff\ufffe")
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------

def split_command_chain(command: str) -> list[str]:
    """Split a command string by shell operators (&&, ||, ;, |).

    Returns individual command segments with leading/trailing whitespace stripped.
    Pipe (|) chains are treated as a single segment led by the first command,
    because blocking only the piped-to portion would be confusing.
    """
    # Split by && || ; but NOT by single |
    # We want "echo foo | python" to be caught as a whole, but
    # "cmd1 && python script.py" to be split into ["cmd1", "python script.py"]
    segments = re.split(r"\s*(?:&&|\|\||;)\s*", command)
    return [s.strip() for s in segments if s.strip()]


def extract_leading_command(segment: str) -> str:
    """Extract the command name from the beginning of a shell segment.

    Skips leading environment variable assignments (FOO=bar).
    """
    tokens = segment.split()
    for token in tokens:
        # Skip env var assignments like PYTHONPATH=/foo
        if "=" in token and not token.startswith("="):
            continue
        return token
    return ""


# ---------------------------------------------------------------------------
# Block rules
# ---------------------------------------------------------------------------

# コマンド位置でブロックする実行ファイル名 → deny メッセージ
BLOCKED_COMMANDS: dict[str, str] = {
    "python": "Use 'uv run python' instead of 'python'. Example: uv run python script.py",
    "python3": "Use 'uv run python' instead of 'python3'. Example: uv run python script.py",
    "pip": "Use 'uv add' to install packages, or 'uv pip' for other pip operations",
    "pip3": "Use 'uv add' to install packages, or 'uv pip' for other pip operations",
}


def check_command(command: str) -> str | None:
    """Check if a command string contains blocked Python invocations.

    Returns a deny reason if blocked, None if allowed.
    """
    stripped = command.strip()

    # コマンド全体が uv で始まる場合は早期 allow（uv run python 等は正当）
    if stripped.startswith("uv ") or stripped == "uv":
        return None

    for segment in split_command_chain(stripped):
        # セグメントが uv で始まる場合もスキップ
        if segment.startswith("uv ") or segment == "uv":
            continue

        lead = extract_leading_command(segment)
        if lead in BLOCKED_COMMANDS:
            return BLOCKED_COMMANDS[lead]

        # パイプの右側もチェック: "echo foo | python script.py"
        pipe_parts = segment.split("|")
        for part in pipe_parts[1:]:
            piped_lead = extract_leading_command(part.strip())
            if piped_lead in BLOCKED_COMMANDS:
                return BLOCKED_COMMANDS[piped_lead]

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

    # bash / powershell コマンド以外は対象外
    if tool_name not in ("bash", "powershell"):
        allow()

    tool_args_raw = input_data.get("toolArgs", {})
    if isinstance(tool_args_raw, str):
        try:
            tool_args = json.loads(tool_args_raw)
        except (json.JSONDecodeError, ValueError):
            tool_args = {}
    else:
        tool_args = tool_args_raw if isinstance(tool_args_raw, dict) else {}

    command: str = tool_args.get("command", "")
    if not command:
        allow()

    reason = check_command(command)
    if reason:
        deny(reason)

    allow()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        deny("Hook script error - fail-safe deny")
