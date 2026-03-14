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
# Match one shell-ish token composed of unquoted text, double-quoted text,
# and/or single-quoted text, so paths with spaces remain intact.
# Quoted spans also allow backslash escapes such as \" and \'.
COMMAND_TOKEN_RE = re.compile(r"""(?:[^\s"']+|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')+""")

# ---------------------------------------------------------------------------
# Environment variable access blocking
# ---------------------------------------------------------------------------

# Commands that dump all environment variables.
ENV_DUMP_COMMANDS: frozenset[str] = frozenset({
    "printenv",
})

# Commands that dump all variables when invoked *without meaningful arguments*.
# ``env`` is allowed with ``-i`` / ``-u`` / ``--`` (environment manipulation),
# so only a bare ``env`` (optionally with trailing pipe) is blocked.
_BARE_ENV_RE = re.compile(
    r"(?:^|\s*(?:&&|\|\||;)\s*)"  # start or after shell operator
    r"env"
    r"(?:\s*(?:\||;|&&|\|\||$))",  # followed by pipe, operator, or end
)

# ``set`` without arguments dumps all variables; ``set -e`` etc. is fine.
_BARE_SET_RE = re.compile(
    r"(?:^|\s*(?:&&|\|\||;)\s*)"
    r"set"
    r"(?:\s*(?:\||;|&&|\|\||$))",
)

# Full-variable enumeration builtins.
_ENUM_BUILTINS_RE = re.compile(
    r"\b(?:declare|typeset)\s+-p\b"
    r"|\bexport\s+-p\b"
    r"|\bcompgen\s+-[ve]\b",
)

# Language-runtime patterns that dump the *entire* environment mapping.
_RUNTIME_ENV_DUMP_RE = re.compile(
    r"\bos\.environ\b"         # Python  os.environ  (whole mapping)
    r"|\bos\.getenv\(\s*\)"    # Python  os.getenv() with no arg
    r"|\bprocess\.env\b"       # Node.js process.env (whole object)
    r"|%ENV\b"                 # Perl    %ENV
    r"|\bENV\.to_h\b"         # Ruby    ENV.to_h
    r"|\bENV\.each\b"         # Ruby    ENV.each
    r"|\bSystem\.getenv\(\s*\)"  # Java  System.getenv()
    r"|\bDeno\.env\.toObject\b"  # Deno  Deno.env.toObject()
    r"|\bGet-ChildItem\s+Env:"   # PowerShell Get-ChildItem Env:
    r"|\\\$env:",              # PowerShell $env: variable access
    re.IGNORECASE,
)

# Sensitive variable name fragments.  If a shell expansion ``$VAR`` or
# ``${VAR}`` contains one of these (case-insensitive), it is blocked.
_SENSITIVE_FRAGMENTS: frozenset[str] = frozenset({
    "secret", "token", "key", "password", "credential",
    "api_key", "apikey", "access_key", "accesskey",
    "private_key", "privatekey",
    "connection_string", "connectionstring",
    "client_secret", "clientsecret",
    "db_password", "dbpassword",
    "auth",
})

# Safe variable names that are never blocked even if they match fragments
# above (e.g. ``SSH_AUTH_SOCK`` contains ``auth``).
_SAFE_VARIABLES: frozenset[str] = frozenset({
    "path", "home", "shell", "user", "logname",
    "lang", "language", "lc_all", "lc_ctype", "lc_messages",
    "term", "colorterm",
    "pwd", "oldpwd", "tmpdir",
    "editor", "visual", "pager",
    "hostname", "hosttype", "ostype", "machtype",
    "display", "wayland_display",
    "xdg_config_home", "xdg_data_home", "xdg_cache_home",
    "xdg_runtime_dir", "xdg_state_home",
    "xdg_current_desktop", "xdg_session_type",
    "node_env", "npm_config_prefix",
    "gopath", "goroot",
    "cargo_home", "rustup_home",
    "ssh_auth_sock", "ssh_agent_pid",
    "shlvl", "lines", "columns",
    "histsize", "histfile", "histcontrol",
    "ps1", "ps2", "ps4",
    "ifs",
    "uid", "euid", "groups",
    "browser", "http_proxy", "https_proxy", "no_proxy",
    "ftp_proxy", "all_proxy",
    "mise_shell",
    "_",  # last command
})

# Regex that captures ``$VAR`` or ``${VAR}`` references.
_SHELL_VAR_REF_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


def _is_sensitive_var(name: str) -> bool:
    """Return True if *name* looks like a secret variable."""
    lower = name.lower()
    if lower in _SAFE_VARIABLES:
        return False
    return any(frag in lower for frag in _SENSITIVE_FRAGMENTS)


def check_env_access(command: str) -> str | None:
    """Detect environment-variable access patterns in a shell command.

    Returns a deny reason string when the command appears to read
    environment variables in a way that could leak secrets, or ``None``
    if the command looks safe.
    """
    stripped = command.strip()
    if not stripped:
        return None

    # --- 1. Dump-all commands in leading position (per shell segment) ---
    # Split by shell operators so ``ls && printenv`` catches ``printenv``.
    segments = re.split(r"\s*(?:&&|\|\||;)\s*", stripped)
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        # Also look past pipes — ``foo | printenv`` should be caught.
        pipe_parts = seg.split("|")
        for part in pipe_parts:
            part = part.strip()
            if not part:
                continue
            seg_tokens = part.split()
            seg_lead = seg_tokens[0] if seg_tokens else ""
            if seg_lead in ENV_DUMP_COMMANDS:
                return f"Blocked env dump command: {seg_lead}"
            if seg_lead == "env":
                if len(seg_tokens) == 1:
                    return "Blocked env dump command: env (use 'env -i' to run with clean environment)"
                second = seg_tokens[1]
                if not (second.startswith("-") or "=" in second or second == "--"):
                    return "Blocked env dump command: env (use 'env -i' to run with clean environment)"

    if _BARE_SET_RE.search(stripped):
        return "Blocked env dump command: set (without arguments lists all variables)"

    # --- 2. Enumeration builtins ---
    if _ENUM_BUILTINS_RE.search(stripped):
        return "Blocked env enumeration builtin"

    # --- 3. Runtime env dump patterns ---
    m = _RUNTIME_ENV_DUMP_RE.search(stripped)
    if m:
        return f"Blocked runtime env dump pattern: {m.group(0)}"

    # --- 4. Sensitive variable expansion ---
    for var_match in _SHELL_VAR_REF_RE.finditer(stripped):
        var_name = var_match.group(1)
        if _is_sensitive_var(var_name):
            return f"Blocked sensitive variable reference: ${var_name}"

    return None


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
    - Compiled patterns are cached because the same blocked globs are reused
      across multiple path and command checks within one hook invocation.
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
                    # Match zero or more directory segments for the special ``**/`` case.
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
    """Extract path-like command tokens while preserving quoted substrings."""
    candidates: list[str] = []
    for token in COMMAND_TOKEN_RE.findall(command):
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

    # --- Environment variable access check (bash / powershell only) ---
    if tool_name in ("bash", "powershell") and command:
        env_hit = check_env_access(command)
        if env_hit:
            deny(env_hit)

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
