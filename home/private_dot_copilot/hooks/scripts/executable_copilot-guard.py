# /// script
# requires-python = ">=3.9"
# ///
"""Copilot Guard — cross-platform preToolUse hook (bash / powershell).

Reads a JSON tool-call from stdin, checks against blocked-files.txt and
allowed-urls.txt, and emits a JSON permission decision on stdout.

Run via: uv run copilot-guard.py
"""
from __future__ import annotations

from functools import lru_cache
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

COMMAND_STRIP_CHARS = "\"'`()[]{};,"


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


def normalize_pattern(pattern: str) -> str:
    """Normalize a blocked-files glob pattern to a canonical POSIX form."""
    normalized = pattern.strip().replace("\\", "/")
    normalized = re.sub(r"/+", "/", normalized)
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def normalize_path(value: str) -> str:
    """Normalize path-like values from tool args for cross-platform matching."""
    normalized = value.strip().strip("\"'")
    if normalized.lower().startswith("file://"):
        parsed = urlsplit(normalized)
        normalized = unquote(parsed.path)
        if parsed.netloc:
            normalized = f"{parsed.netloc}/{normalized.lstrip('/')}"
    normalized = normalized.replace("\\", "/")
    normalized = re.sub(r"/+", "/", normalized)
    while normalized.startswith("./"):
        normalized = normalized[2:]
    # file:// URIs on Windows are parsed as /C:/path, so drop that extra slash.
    if re.match(r"^/[A-Za-z]:/", normalized):
        normalized = normalized[1:]
    return normalized.lstrip("/")


@lru_cache(maxsize=None)
def compile_glob(pattern: str) -> re.Pattern[str]:
    """Compile a path-aware glob pattern.

    Rules:
    - ``*`` matches within one path segment.
    - ``?`` matches one character within one path segment.
    - ``**`` matches across path segments.
    """
    normalized = normalize_pattern(pattern)
    parts = ["^"]
    index = 0
    while index < len(normalized):
        char = normalized[index]
        if char == "*":
            if index + 1 < len(normalized) and normalized[index + 1] == "*":
                index += 2
                if index < len(normalized) and normalized[index] == "/":
                    index += 1
                    # Match zero or more directory segments, including the empty prefix.
                    parts.append("(?:[^/]+/)*")
                else:
                    parts.append(".*")
                continue
            parts.append("[^/]*")
        elif char == "?":
            parts.append("[^/]")
        elif char == "/":
            parts.append("/")
        else:
            parts.append(re.escape(char))
        index += 1
    parts.append("$")
    return re.compile("".join(parts))


def matches_blocked_pattern(target: str, pattern: str) -> bool:
    """Return True when a normalized target path matches a blocked glob."""
    normalized_target = normalize_path(target)
    if not normalized_target:
        return False
    return bool(compile_glob(pattern).match(normalized_target))


# ---------------------------------------------------------------------------
# Blocked-file checks
# ---------------------------------------------------------------------------

def check_blocked_path(target: str, patterns: list[str]) -> str | None:
    """Path-aware glob match for path arguments."""
    for pat in patterns:
        if matches_blocked_pattern(target, pat):
            return pat
    return None


def extract_command_candidates(command: str) -> list[str]:
    """Extract path-like command tokens without relying on shell-specific parsing."""
    candidates: list[str] = []
    for token in command.split():
        cleaned = token.strip(COMMAND_STRIP_CHARS)
        if not cleaned:
            continue
        candidates.append(cleaned)
        if "=" in cleaned:
            _, rhs = cleaned.rsplit("=", 1)
            if rhs:
                candidates.append(rhs)
    return candidates


def check_blocked_command(target: str, patterns: list[str]) -> str | None:
    """Path-aware glob match for command arguments."""
    candidates = extract_command_candidates(target)
    for pat in patterns:
        if any(matches_blocked_pattern(candidate, pat) for candidate in candidates):
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

    # --- Check path-like properties (path-aware glob match) ---
    for prop in ("path", "file", "uri", "glob"):
        val = tool_args.get(prop, "")
        if val:
            hit = check_blocked_path(val, blocked_patterns)
            if hit:
                deny(f"Blocked pattern: {hit}")

    # --- Check command property (path-aware glob match) ---
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
