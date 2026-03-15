# /// script
# requires-python = ">=3.9"
# ///
"""Copilot Audit Log — postToolUse hook for recording tool invocations.

Reads a JSON tool-call from stdin and appends a one-line JSON log entry to
~/.copilot/audit.jsonl. The postToolUse output is ignored by Copilot CLI,
so this script is purely for logging/auditing purposes.

Security: Sensitive patterns (tokens, secrets, auth headers) are redacted
before writing to prevent the audit log from becoming a secondary secret store.

Run via: uv run audit-log.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Maximum audit log file size before rotation (default: 50 MB)
MAX_LOG_BYTES = int(os.environ.get("COPILOT_AUDIT_MAX_BYTES", 50 * 1024 * 1024))

# Patterns to redact from logged values
_REDACT_PATTERNS = re.compile(
    r"(?i)"
    r"(?:"
    # Auth headers: "Authorization: Bearer xxx" or "Authorization: Basic xxx"
    r"authorization[=:\s]+\S+(?:\s+\S+){0,2}"
    # Key-value: "token=xxx", "secret: xxx", "password=xxx"
    r"|(?:bearer|token|basic|key|secret|password)[=:\s]+\S+"
    r"|ghp_\S+"           # GitHub PAT
    r"|github_pat_\S+"    # GitHub fine-grained PAT
    r"|ghu_\S+|ghs_\S+"   # GitHub App tokens
    r"|xox[bprs]-\S+"     # Slack tokens
    r"|sk-[A-Za-z0-9]{20,}"  # OpenAI API keys
    r"|DefaultEndpointsProtocol=\S+"  # Azure connection strings
    r"|AccountKey=[A-Za-z0-9+/=]+"    # Azure storage keys
    r"|SharedAccessSignature=\S+"     # Azure SAS
    r")"
)


def redact(value: str) -> str:
    """Replace sensitive patterns with [REDACTED]."""
    return _REDACT_PATTERNS.sub("[REDACTED]", value)


def rotate_if_needed(log_file: Path) -> None:
    """Rotate the log file if it exceeds the size threshold."""
    try:
        if log_file.exists() and log_file.stat().st_size > MAX_LOG_BYTES:
            rotated = log_file.with_suffix(".jsonl.1")
            # Simple single-file rotation: overwrite previous rotated file
            if rotated.exists():
                rotated.unlink()
            log_file.rename(rotated)
    except Exception:
        pass  # Best-effort; never block agent operation


def main() -> None:
    log_dir = Path(os.environ.get("COPILOT_AUDIT_DIR", Path.home() / ".copilot"))
    log_file = log_dir / "audit.jsonl"

    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return
        data = json.loads(raw)
    except Exception:
        return  # postToolUse output is ignored; silently skip on bad input

    tool_name: str = data.get("toolName", "unknown")
    tool_args = data.get("toolArgs", {})

    # Extract a brief summary of the tool call (avoid logging full file contents)
    summary: dict[str, str] = {"tool": tool_name}
    if isinstance(tool_args, dict):
        for key in ("command", "path", "file", "url", "pattern", "query"):
            val = tool_args.get(key)
            if val and isinstance(val, str):
                # Truncate long values to avoid bloating the log
                truncated = val[:500] if len(val) > 500 else val
                summary[key] = redact(truncated)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "cwd": os.getcwd(),
        **summary,
    }

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        rotate_if_needed(log_file)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Best-effort logging; never block agent operation


if __name__ == "__main__":
    main()
