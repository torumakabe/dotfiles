# /// script
# requires-python = ">=3.9"
# ///
"""Copilot Guard — cross-platform preToolUse hook (bash / powershell).

Reads a JSON tool-call from stdin, checks against blocked-files.txt and
allowed-urls.txt, and emits a JSON permission decision on stdout.

Run via: uv run copilot-guard.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


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
    # Windows PowerShell may default to CP932; force UTF-8
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

    raw = sys.stdin.read().strip()
    # Strip BOM if present
    raw = raw.lstrip("\ufeff\ufffe")
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Config file loaders
# ---------------------------------------------------------------------------

def load_patterns(path: Path) -> list[str]:
    """Load non-empty, non-comment lines from a config file."""
    if not path.is_file():
        return []
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def pattern_to_substring(pattern: str) -> str:
    """Extract the fixed substring from a glob-like pattern for matching."""
    short = pattern.lstrip("*").lstrip("/")
    short = short.rstrip("*")
    # Remove remaining glob chars
    clean = short.replace("*", "").replace("?", "")
    return clean


# ---------------------------------------------------------------------------
# Blocked-file checks
# ---------------------------------------------------------------------------

def check_blocked_path(target: str, patterns: list[str]) -> str | None:
    """Strict substring match for path arguments."""
    for pat in patterns:
        sub = pattern_to_substring(pat)
        if sub and sub in target:
            return pat
    return None


def check_blocked_command(target: str, patterns: list[str]) -> str | None:
    """Boundary-aware match for command strings.

    Uses path separators, whitespace, quotes, shell metacharacters, and
    assignment operators as word boundaries to avoid false positives on
    substrings like ``os.environ``.
    """
    for pat in patterns:
        sub = pattern_to_substring(pat)
        if not sub:
            continue
        escaped = re.escape(sub)
        boundary = r"""(?:^|[\\/\s"';|&()`=$])"""
        if re.search(boundary + escaped, target):
            return pat
    return None


# ---------------------------------------------------------------------------
# URL allowlist
# ---------------------------------------------------------------------------

def extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s\"']+", text)


def url_host(url: str) -> str:
    # Simple host extraction without urllib (no external deps)
    host = re.sub(r"^https?://", "", url)
    host = host.split("/")[0].split(":")[0]
    return host


def is_url_allowed(url: str, allowed_domains: list[str]) -> bool:
    host = url_host(url)
    for domain in allowed_domains:
        if host == domain or host.endswith("." + domain):
            return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        input_data = read_input()
    except Exception:
        deny("Failed to parse input - fail-safe deny")

    tool_name: str = input_data.get("toolName", "")
    tool_args_raw = input_data.get("toolArgs", {})

    # toolArgs may be a JSON string — re-parse if so
    if isinstance(tool_args_raw, str):
        try:
            tool_args = json.loads(tool_args_raw)
        except (json.JSONDecodeError, ValueError):
            tool_args = {}
    else:
        tool_args = tool_args_raw if isinstance(tool_args_raw, dict) else {}

    # Locate config files relative to this script
    script_dir = Path(__file__).resolve().parent
    hooks_dir = script_dir.parent
    blocked_file = hooks_dir / "blocked-files.txt"
    allowed_file = hooks_dir / "allowed-urls.txt"

    if not blocked_file.is_file():
        deny("blocked-files.txt not found - fail-safe deny")

    blocked_patterns = load_patterns(blocked_file)
    allowed_domains = load_patterns(allowed_file)

    # --- Check path-like properties (strict match) ---
    for prop in ("path", "file", "uri", "glob"):
        val = tool_args.get(prop, "")
        if val:
            hit = check_blocked_path(val, blocked_patterns)
            if hit:
                deny(f"Blocked pattern: {hit}")

    # --- Check command property (boundary-aware match) ---
    command: str = tool_args.get("command", "")
    if command:
        hit = check_blocked_command(command, blocked_patterns)
        if hit:
            deny(f"Blocked pattern: {hit}")

    # --- URL allowlist ---
    if allowed_domains:
        if command:
            for url in extract_urls(command):
                if not is_url_allowed(url, allowed_domains):
                    deny(f"URL not in allowlist: {url}")

        if tool_name == "web_fetch":
            url = tool_args.get("url", "")
            if url and not is_url_allowed(url, allowed_domains):
                deny(f"URL not in allowlist: {url}")

    allow()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Catch-all: fail-safe deny (mirrors bash trap ERR)
        deny("Hook script error - fail-safe deny")
