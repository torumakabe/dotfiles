# /// script
# requires-python = ">=3.13"
# ///
"""Copilot Guard — cross-platform preToolUse hook (bash / powershell).

Reads a JSON tool-call from stdin, checks against allowed-files.txt,
blocked-files.txt, and ask-files.txt, and emits a JSON permission decision
on stdout.

Architecture:
    Each security check is implemented as a *checker function* with the
    signature ``(CheckContext) -> CheckResult | None``.  Returning a
    ``CheckResult`` means "deny or ask with this reason"; returning ``None``
    means "pass".  All checkers are registered in the ``CHECKERS`` list and
    executed in order by ``main()``.  Results are aggregated with the priority
    deny > ask > (no output).  When no checker has an opinion the hook
    produces no output, deferring to the CLI's built-in approval flow.
    To add a new check, write a checker function and append it to
    ``CHECKERS``.

Run via: uv run copilot-guard.py
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, NamedTuple, Optional
from urllib.parse import unquote, urlsplit


# Patterns to redact from audit-denies.jsonl (mirrors audit-log.py / audit-failure.py)
_AUDIT_REDACT_RE = re.compile(
    r"(?i)(?:"
    r"authorization[=:\s]+\S+(?:\s+\S+){0,2}"
    r"|(?:bearer|token|basic|key|secret|password)[=:\s]+\S+"
    r"|ghp_\S+|github_pat_\S+|ghu_\S+|ghs_\S+"
    r"|xox[bprs]-\S+"
    r"|sk-[A-Za-z0-9]{20,}"
    r"|DefaultEndpointsProtocol=\S+"
    r"|AccountKey=[A-Za-z0-9+/=]+"
    r"|SharedAccessSignature=\S+"
    r")"
)
_AUDIT_MAX_BYTES = int(os.environ.get("COPILOT_AUDIT_MAX_BYTES", 50 * 1024 * 1024))


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def deny(reason: str) -> None:
    print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": reason}))
    sys.exit(0)


def ask(reason: str) -> None:
    print(json.dumps({"permissionDecision": "ask", "permissionDecisionReason": reason}))
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


def extract_apply_patch_paths(raw: Any) -> list[str]:
    """Extract target paths from an apply_patch freeform argument."""
    if not isinstance(raw, str):
        raise TypeError("apply_patch toolArgs must be freeform text")

    prefixes = (
        "*** Add File: ",
        "*** Delete File: ",
        "*** Update File: ",
        "*** Move to: ",
    )
    paths: list[str] = []
    for line in raw.splitlines():
        for prefix in prefixes:
            if line.startswith(prefix):
                target = line.removeprefix(prefix).strip()
                if target:
                    paths.append(target)
                break
    return paths


# ---------------------------------------------------------------------------
# Config file loading
# ---------------------------------------------------------------------------

def load_config_lines(path: Path) -> list[str]:
    """Load non-empty, non-comment lines from a config file."""
    if not path.is_file():
        return []
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# CheckResult and CheckContext
# ---------------------------------------------------------------------------

class CheckResult(NamedTuple):
    """Result of a checker function: a decision and the reason for it."""
    decision: str   # "deny" or "ask"
    reason: str


class CheckContext(NamedTuple):
    """Immutable bundle of data available to every checker function."""
    tool_name: str
    tool_args: dict[str, Any]
    command: str
    allowed_patterns: list[str]
    blocked_patterns: list[str]
    ask_patterns: list[str]


# Checker function contract: (CheckContext) -> CheckResult or None.
Checker = Callable[[CheckContext], Optional[CheckResult]]


# ---------------------------------------------------------------------------
# Path normalization and glob matching (shared utilities)
# ---------------------------------------------------------------------------

COMMAND_STRIP_CHARS = "\"'`()[]{};,"
# Match one shell-ish token composed of unquoted text, double-quoted text,
# and/or single-quoted text, so paths with spaces remain intact.
# Quoted spans also allow backslash escapes such as \" and \'.
COMMAND_TOKEN_RE = re.compile(r"""(?:[^\s"']+|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')+""")


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
# Checker: Blocked files
# ---------------------------------------------------------------------------

def check_blocked_path(target: str, patterns: list[str]) -> str | None:
    """Path-aware glob match for path arguments."""
    for pat in patterns:
        if matches_blocked_pattern(target, pat):
            return pat
    return None


def matches_allowed_path(
    target: str,
    patterns: list[str],
    project_root: Path | None = None,
) -> bool:
    """Return True when a path resolves to a project-contained exception."""
    raw_target = target.strip().strip("\"'")
    if raw_target.lower().startswith("file://"):
        return False

    root = (project_root or Path.cwd()).resolve()
    raw_path = Path(raw_target)
    windows_absolute = bool(re.match(r"^[A-Za-z]:[\\/]", raw_target))
    if windows_absolute and os.name != "nt":
        return False

    if raw_path.is_absolute():
        try:
            relative_path = raw_path.relative_to(root)
        except ValueError:
            return False
    else:
        if raw_target.startswith(("/", "\\")) or windows_absolute:
            return False
        relative_path = Path(normalize_path(target))

    if ".." in relative_path.parts:
        return False
    relative_target = relative_path.as_posix()
    if not any(matches_blocked_pattern(relative_target, pattern) for pattern in patterns):
        return False

    candidate = root
    for part in relative_path.parts:
        candidate /= part
        if candidate.is_symlink() or candidate.is_junction():
            return False
    return candidate.resolve(strict=False).is_relative_to(root)


PATH_ARG_KEYS: tuple[str, ...] = ("path", "file", "uri", "glob", "paths", "files", "uris", "globs")


def extract_path_arg_values(tool_args: dict[str, Any]) -> list[str]:
    """Extract path-like string values from scalar and array tool arguments."""
    values: list[str] = []
    for prop in PATH_ARG_KEYS:
        prop_value = tool_args.get(prop)
        if isinstance(prop_value, str):
            values.append(prop_value)
        elif isinstance(prop_value, list):
            values.extend(item for item in prop_value if isinstance(item, str))
    return values


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


def check_blocked_files(ctx: CheckContext) -> CheckResult | None:
    """Check path-like tool args and command tokens against blocked/ask patterns.

    Returns CheckResult("deny", ...) for blocked patterns,
    CheckResult("ask", ...) for ask patterns, or None if no match.
    Blocked patterns are checked first (deny takes priority over ask).
    """
    path_arg_values = extract_path_arg_values(ctx.tool_args)
    path_arg_values = [
        value
        for value in path_arg_values
        if not matches_allowed_path(value, ctx.allowed_patterns)
    ]

    for prop_value in path_arg_values:
        matched_pattern = check_blocked_path(prop_value, ctx.blocked_patterns)
        if matched_pattern:
            return CheckResult("deny", f"Blocked pattern: {matched_pattern}")

    if ctx.command:
        matched_pattern = check_blocked_command(ctx.command, ctx.blocked_patterns)
        if matched_pattern:
            return CheckResult("deny", f"Blocked pattern: {matched_pattern}")

    # Ask patterns (lower priority than deny)
    for prop_value in path_arg_values:
        matched_pattern = check_blocked_path(prop_value, ctx.ask_patterns)
        if matched_pattern:
            return CheckResult("ask", f"Confirm access — matched pattern: {matched_pattern}")

    if ctx.command:
        matched_pattern = check_blocked_command(ctx.command, ctx.ask_patterns)
        if matched_pattern:
            return CheckResult("ask", f"Confirm access — matched pattern: {matched_pattern}")

    return None


# ---------------------------------------------------------------------------
# Checker: Environment variable access
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
    r"|\bDeno\.env\.toObject\b"  # Deno  Deno.env.toObject()
    r"|\bGet-ChildItem\s+Env:",  # PowerShell Get-ChildItem Env:
    re.IGNORECASE,
)

# Sensitive variable name terms. Terms must be separated by underscores or
# span the complete name, so ordinary variables such as ``$author`` are safe.
_SENSITIVE_TERMS: frozenset[str] = frozenset({
    "secret", "token", "key", "password", "credential",
    "api_key", "apikey", "access_key", "accesskey",
    "private_key", "privatekey",
    "connection_string", "connectionstring",
    "client_secret", "clientsecret",
    "db_password", "dbpassword",
    "auth",
})

# Concatenated names have no separator or case transition to identify word
# boundaries. Match only high-signal forms so names such as author, tokens,
# keyword, and monkey remain safe.
_SENSITIVE_CONCATENATED_RE = re.compile(
    r"secret"
    r"|password"
    r"|credential"
    r"|token$"
    r"|auth$"
    r"|(?:api|access|private|ssh|signing|master|session|host|gpg|deploy|encryption)key"
    r"|connectionstring"
)

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

# Regexes that capture environment-variable references by shell syntax.
_POSIX_ENV_VAR_REF_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
_POWERSHELL_ENV_VAR_REF_RE = re.compile(
    r"\$(?:env:([A-Za-z_][A-Za-z0-9_]*)|\{env:([A-Za-z_][A-Za-z0-9_]*)\})",
    re.IGNORECASE,
)


def _is_sensitive_var(name: str) -> bool:
    """Return True if *name* looks like a secret variable."""
    raw_lower = name.lower()
    snake_name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    snake_name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", snake_name)
    lower = snake_name.lower()
    if lower in _SAFE_VARIABLES:
        return False
    separated_match = any(
        re.search(rf"(?:^|_){re.escape(term)}(?:_|$)", lower)
        for term in _SENSITIVE_TERMS
    )
    return separated_match or _SENSITIVE_CONCATENATED_RE.search(raw_lower) is not None


def check_env_access(command: str, shell: str = "bash") -> str | None:
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
    var_ref_re = (
        _POWERSHELL_ENV_VAR_REF_RE
        if shell == "powershell"
        else _POSIX_ENV_VAR_REF_RE
    )
    for var_match in var_ref_re.finditer(stripped):
        if shell == "powershell":
            var_name = var_match.group(1) or var_match.group(2)
        else:
            var_name = var_match.group(1)
        if _is_sensitive_var(var_name):
            prefix = "$env:" if shell == "powershell" else "$"
            return f"Blocked sensitive variable reference: {prefix}{var_name}"

    return None


def check_env(ctx: CheckContext) -> CheckResult | None:
    """Check for environment variable access in shell commands."""
    if ctx.tool_name not in ("bash", "powershell") or not ctx.command:
        return None
    reason = check_env_access(ctx.command, ctx.tool_name)
    if reason:
        return CheckResult("deny", reason)
    return None


# ---------------------------------------------------------------------------
# Checker: git commit approval
# ---------------------------------------------------------------------------

# Git global options that consume the next token as their argument.
_GIT_ARG_OPTIONS: frozenset[str] = frozenset({
    "-c", "-C", "--git-dir", "--work-tree",
    "--namespace", "--super-prefix", "--config-env",
})

# Shell operators that delimit independent commands.
_SHELL_OPERATORS: frozenset[str] = frozenset({"&&", "||", ";", "|"})

# Shell wrapper commands that delegate to the next command on the line.
_SHELL_WRAPPERS: frozenset[str] = frozenset({
    "command", "exec", "nice", "nohup", "time", "sudo",
})


def _normalize_executable(token: str) -> str:
    """Extract the base executable name from a possibly-qualified path.

    Handles ``/usr/bin/git``, ``git.exe``, and quoted variants.
    """
    name = token.strip("\"'")
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return name


def _has_git_commit(command: str) -> bool:
    """Return True if *command* contains a ``git commit`` invocation.

    Uses the quote-aware ``COMMAND_TOKEN_RE`` tokenizer so that shell
    operators inside quoted strings are not treated as command separators.
    Skips ``env``, ``command``, ``sudo`` and other common shell wrappers,
    and normalises the executable name (basename, strip ``.exe``).
    """
    tokens = COMMAND_TOKEN_RE.findall(command.strip())

    # Split token list into segments by shell operators.
    segments: list[list[str]] = [[]]
    for tok in tokens:
        if tok in _SHELL_OPERATORS:
            segments.append([])
        else:
            segments[-1].append(tok)

    for seg in segments:
        if not seg:
            continue
        idx = 0
        # Skip env-var assignments before the command (VAR=value …).
        while idx < len(seg) and re.match(r"^[A-Za-z_]\w*=", seg[idx]):
            idx += 1
        if idx >= len(seg):
            continue
        # Skip shell wrappers (env, command, sudo, …).
        while idx < len(seg):
            name = _normalize_executable(seg[idx])
            if name == "env":
                idx += 1
                # Skip env's own flags and VAR=value arguments.
                while idx < len(seg):
                    t = seg[idx]
                    if t.startswith("-") or re.match(r"^[A-Za-z_]\w*=", t):
                        idx += 1
                        continue
                    break
                continue
            if name in _SHELL_WRAPPERS:
                idx += 1
                while idx < len(seg) and seg[idx].startswith("-"):
                    idx += 1
                continue
            break
        if idx >= len(seg):
            continue
        # Check if the resolved command is git.
        if _normalize_executable(seg[idx]) != "git":
            continue
        # Walk past git global options to find the subcommand.
        idx += 1
        while idx < len(seg):
            tok = seg[idx]
            if not tok.startswith("-"):
                break
            if tok in _GIT_ARG_OPTIONS:
                idx += 1  # skip the option's argument
            idx += 1
        if idx < len(seg) and seg[idx] == "commit":
            return True
    return False


def check_git_commit(ctx: CheckContext) -> CheckResult | None:
    """Require explicit user approval for ``git commit`` commands."""
    if ctx.tool_name not in ("bash", "powershell") or not ctx.command:
        return None
    if _has_git_commit(ctx.command):
        return CheckResult("ask", "git commit requires user approval")
    return None


# ---------------------------------------------------------------------------
# Checker registry
# ---------------------------------------------------------------------------

CHECKERS: list[Checker] = [
    check_blocked_files,
    check_env,
    check_git_commit,
]


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def build_context() -> CheckContext:
    """Read stdin, load config files, and return an immutable CheckContext."""
    try:
        input_data = read_input()
    except Exception:
        deny("Failed to parse input - fail-safe deny")

    tool_name: str = input_data.get("toolName", "")
    raw_tool_args = input_data.get("toolArgs", {})
    if tool_name == "apply_patch":
        tool_args = {"paths": extract_apply_patch_paths(raw_tool_args)}
    else:
        tool_args = parse_tool_args(raw_tool_args)
    command: str = tool_args.get("command", "")

    script_dir = Path(__file__).resolve().parent
    hooks_dir = script_dir.parent
    allowed_file = hooks_dir / "allowed-files.txt"
    blocked_file = hooks_dir / "blocked-files.txt"
    ask_file = hooks_dir / "ask-files.txt"

    if not blocked_file.is_file():
        deny("blocked-files.txt not found - fail-safe deny")

    return CheckContext(
        tool_name=tool_name,
        tool_args=tool_args,
        command=command,
        allowed_patterns=load_config_lines(allowed_file),
        blocked_patterns=load_config_lines(blocked_file),
        ask_patterns=load_config_lines(ask_file),
    )


# ---------------------------------------------------------------------------
# Audit logging (deny events only; best-effort)
# ---------------------------------------------------------------------------

def _log_deny(ctx: CheckContext, reason: str) -> None:
    """Append a deny event to audit-denies.jsonl. Never raises."""
    try:
        log_dir = Path(os.environ.get("COPILOT_AUDIT_DIR", Path.home() / ".copilot"))
        log_file = log_dir / "audit-denies.jsonl"
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "cwd": os.getcwd(),
            "tool": ctx.tool_name,
            "reason": reason,
        }
        # Capture the denied target(s): command for shell, plus path/url/etc. for file tools.
        if ctx.command:
            entry["command"] = _AUDIT_REDACT_RE.sub("[REDACTED]", ctx.command[:500])
        if isinstance(ctx.tool_args, dict):
            for key in ("path", "file", "url", "pattern", "query"):
                val = ctx.tool_args.get(key)
                if val and isinstance(val, str):
                    truncated = val[:500] if len(val) > 500 else val
                    entry[key] = _AUDIT_REDACT_RE.sub("[REDACTED]", truncated)
        log_dir.mkdir(parents=True, exist_ok=True)
        if log_file.exists() and log_file.stat().st_size > _AUDIT_MAX_BYTES:
            rotated = log_file.with_suffix(".jsonl.1")
            if rotated.exists():
                rotated.unlink()
            log_file.rename(rotated)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ctx = build_context()
    results: list[CheckResult] = []
    for checker in CHECKERS:
        result = checker(ctx)
        if result:
            results.append(result)
    if not results:
        return  # No opinion — let the CLI's default approval flow decide
    # Priority: deny > ask > no opinion (empty stdout)
    denies = [r for r in results if r.decision == "deny"]
    if denies:
        _log_deny(ctx, denies[0].reason)
        deny(denies[0].reason)
    asks = [r for r in results if r.decision == "ask"]
    if asks:
        ask(asks[0].reason)
    # All results are neither deny nor ask — defer to CLI default
    return


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Catch-all: fail-safe deny (mirrors bash trap ERR)
        deny("Hook script error - fail-safe deny")
