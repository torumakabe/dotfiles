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
import shlex
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
COMMAND_PUNCTUATION = ";&|()<>"
COMMAND_PUNCTUATION_RE = re.compile(r"^[;&|()<>]+$")
_CONSERVATIVE_TOKEN_RE = re.compile(r"\S+")


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
    """Return True when a path resolves inside the hook's configured cwd."""
    resolved_path = _project_relative_path(target, project_root)
    if resolved_path is None:
        return False
    root, relative_path = resolved_path
    relative_target = relative_path.as_posix()
    if not any(
        not _PATH_GLOB_META_RE.search(pattern)
        and matches_blocked_pattern(relative_target, pattern)
        for pattern in patterns
    ):
        return False
    return _path_has_no_links(root, relative_path)


def _project_relative_path(
    target: str,
    project_root: Path | None = None,
) -> tuple[Path, Path] | None:
    """Resolve a literal path to a project-relative path without following links."""
    raw_target = target.strip().strip("\"'")
    if not raw_target or raw_target.lower().startswith("file://"):
        return None

    root = (project_root or Path.cwd()).resolve()
    raw_path = Path(raw_target)
    windows_absolute = bool(re.match(r"^[A-Za-z]:[\\/]", raw_target))
    if windows_absolute and os.name != "nt":
        return None

    if raw_path.is_absolute():
        try:
            relative_path = raw_path.relative_to(root)
        except ValueError:
            return None
    else:
        if raw_target.startswith(("/", "\\")) or windows_absolute:
            return None
        relative_path = Path(normalize_path(target))

    if ".." in relative_path.parts:
        return None
    return root, relative_path


def _path_has_no_links(root: Path, relative_path: Path) -> bool:
    """Return True when every path component stays inside root without links."""
    candidate = root
    for part in relative_path.parts:
        candidate /= part
        if candidate.is_symlink() or candidate.is_junction():
            return False
    return candidate.resolve(strict=False).is_relative_to(root)


def is_project_contained_path(
    target: str,
    project_root: Path | None = None,
) -> bool:
    """Return True for a literal project-contained path without links."""
    resolved_path = _project_relative_path(target, project_root)
    if resolved_path is None:
        return False
    return _path_has_no_links(*resolved_path)


PATH_ARG_KEYS: tuple[str, ...] = (
    "path",
    "file",
    "uri",
    "glob",
    "paths",
    "files",
    "uris",
    "globs",
)
FILE_PATH_TOOL_NAMES = frozenset(("view", "apply_patch", "edit", "create", "write"))
READ_ONLY_SEARCH_FILTER_ARG_KEYS = {
    "rg": ("glob", "globs"),
    "glob": ("pattern",),
}
READ_ONLY_SEARCH_ROOT_ARG_KEYS = {
    "rg": ("paths",),
    "glob": ("paths",),
}
READ_ONLY_SEARCH_TOOL_NAMES = frozenset(READ_ONLY_SEARCH_FILTER_ARG_KEYS)
ALLOWED_PATH_TOOL_NAMES = FILE_PATH_TOOL_NAMES | READ_ONLY_SEARCH_TOOL_NAMES
_PATH_GLOB_META_RE = re.compile(r"[*?\[\]{}]")


def extract_path_arg_items(
    tool_name: str,
    tool_args: dict[str, Any],
) -> list[tuple[str, str]]:
    """Extract keyed path-like strings, including tool-specific search filters."""
    keys = PATH_ARG_KEYS + tuple(READ_ONLY_SEARCH_FILTER_ARG_KEYS.get(tool_name, ()))
    items: list[tuple[str, str]] = []
    for prop in dict.fromkeys(keys):
        prop_value = tool_args.get(prop)
        if isinstance(prop_value, str):
            items.append((prop, prop_value))
        elif isinstance(prop_value, list):
            items.extend(
                (prop, item) for item in prop_value if isinstance(item, str)
            )
    return items


def _search_roots_are_project_contained(
    tool_name: str,
    tool_args: dict[str, Any],
) -> bool:
    """Validate search roots before allowing an exact path filter exception."""
    raw_roots = [
        tool_args[key]
        for key in READ_ONLY_SEARCH_ROOT_ARG_KEYS[tool_name]
        if key in tool_args
    ]
    if not raw_roots:
        return True
    roots: list[str] = []
    for value in raw_roots:
        if isinstance(value, str):
            roots.append(value)
        elif isinstance(value, list):
            string_roots = [root for root in value if isinstance(root, str)]
            if len(string_roots) != len(value):
                return False
            roots.extend(string_roots)
        else:
            return False
    return bool(roots) and all(
        not _PATH_GLOB_META_RE.search(root) and is_project_contained_path(root)
        for root in roots
    )


def _allowed_path_exception_applies(
    ctx: CheckContext,
    arg_name: str,
    value: str,
) -> bool:
    """Apply allowed paths only to explicit tools and literal project paths."""
    if ctx.tool_name not in ALLOWED_PATH_TOOL_NAMES:
        return False
    if ctx.tool_name in FILE_PATH_TOOL_NAMES:
        return matches_allowed_path(value, ctx.allowed_patterns)
    if _PATH_GLOB_META_RE.search(value):
        return False
    if not matches_allowed_path(value, ctx.allowed_patterns):
        return False
    filter_keys = READ_ONLY_SEARCH_FILTER_ARG_KEYS[ctx.tool_name]
    return arg_name not in filter_keys or _search_roots_are_project_contained(
        ctx.tool_name,
        ctx.tool_args,
    )


def _conservative_tokenize(command: str) -> list[str]:
    """Tokenize malformed input without treating quote characters as protection."""
    return [
        token.replace('"', "").replace("'", "")
        for token in _CONSERVATIVE_TOKEN_RE.findall(command)
    ]


def _tokenize_powershell(command: str) -> list[str]:
    """Tokenize PowerShell argument-mode quotes without expanding expressions."""
    tokens: list[str] = []
    current: list[str] = []
    state = "unquoted"
    index = 0

    def finish_token() -> None:
        if current:
            tokens.append("".join(current))
            current.clear()

    while index < len(command):
        char = command[index]
        if state == "single":
            if char == "'":
                if index + 1 < len(command) and command[index + 1] == "'":
                    current.append("'")
                    index += 2
                    continue
                state = "unquoted"
            else:
                current.append(char)
            index += 1
            continue

        if state == "double":
            if char == '"':
                state = "unquoted"
            elif char == "`" and index + 1 < len(command):
                current.append(command[index + 1])
                index += 2
                continue
            else:
                current.append(char)
            index += 1
            continue

        if char.isspace():
            finish_token()
        elif char in COMMAND_PUNCTUATION:
            finish_token()
            punctuation = [char]
            while (
                index + 1 < len(command)
                and command[index + 1] in COMMAND_PUNCTUATION
            ):
                index += 1
                punctuation.append(command[index])
            tokens.append("".join(punctuation))
        elif char == "'":
            state = "single"
        elif char == '"':
            state = "double"
        elif char == "`" and index + 1 < len(command):
            current.append(command[index + 1])
            index += 1
        else:
            current.append(char)
        index += 1

    if state != "unquoted":
        return _conservative_tokenize(command)
    finish_token()
    return tokens


def tokenize_command(command: str, shell: str = "bash") -> list[str]:
    """Return shell-effective literal tokens without evaluating the command."""
    if shell == "powershell":
        return _tokenize_powershell(command)

    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
        lexer.commenters = ""
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return _conservative_tokenize(command)


def _command_segments(tokens: list[str]) -> list[list[str]]:
    """Split tokens at shell punctuation, including combined operators."""
    segments: list[list[str]] = [[]]
    for token in tokens:
        if COMMAND_PUNCTUATION_RE.fullmatch(token):
            segments.append([])
        else:
            segments[-1].append(token)
    return segments


def extract_command_candidates(command: str, shell: str | None = None) -> list[str]:
    """Extract path-like command tokens using the selected shell's quote rules."""
    candidates: list[str] = []
    tokens = tokenize_command(command, shell or "bash")

    for token in tokens:
        if COMMAND_PUNCTUATION_RE.fullmatch(token):
            continue
        cleaned = token.strip(COMMAND_STRIP_CHARS)
        if not cleaned:
            continue
        candidates.append(cleaned)
        if "=" in cleaned:
            _, rhs = cleaned.rsplit("=", 1)
            if rhs:
                candidates.append(rhs)
    return candidates


def check_blocked_command(
    target: str,
    patterns: list[str],
    shell: str | None = None,
) -> str | None:
    """Path-aware glob match for command arguments."""
    candidates = extract_command_candidates(target, shell)
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
    path_arg_items = extract_path_arg_items(ctx.tool_name, ctx.tool_args)
    if ctx.tool_name in ALLOWED_PATH_TOOL_NAMES:
        path_arg_items = [
            (arg_name, value)
            for arg_name, value in path_arg_items
            if not _allowed_path_exception_applies(ctx, arg_name, value)
        ]

    for _, prop_value in path_arg_items:
        matched_pattern = check_blocked_path(prop_value, ctx.blocked_patterns)
        if matched_pattern:
            display_path = normalize_path(prop_value)[:500]
            return CheckResult(
                "deny",
                f"Blocked pattern: {matched_pattern} (path: {display_path})",
            )

    if ctx.command:
        matched_pattern = check_blocked_command(
            ctx.command,
            ctx.blocked_patterns,
            ctx.tool_name,
        )
        if matched_pattern:
            return CheckResult("deny", f"Blocked pattern: {matched_pattern}")

    # Ask patterns (lower priority than deny)
    for _, prop_value in path_arg_items:
        matched_pattern = check_blocked_path(prop_value, ctx.ask_patterns)
        if matched_pattern:
            return CheckResult("ask", f"Confirm access — matched pattern: {matched_pattern}")

    if ctx.command:
        matched_pattern = check_blocked_command(
            ctx.command,
            ctx.ask_patterns,
            ctx.tool_name,
        )
        if matched_pattern:
            return CheckResult("ask", f"Confirm access — matched pattern: {matched_pattern}")

    return None


# ---------------------------------------------------------------------------
# Checker: git commit approval
# ---------------------------------------------------------------------------

# Git global options that consume the next token as their argument.
_GIT_ARG_OPTIONS: frozenset[str] = frozenset({
    "-c", "-C", "--git-dir", "--work-tree",
    "--namespace", "--super-prefix", "--config-env",
})

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


def _has_git_commit(command: str, shell: str = "bash") -> bool:
    """Return True if *command* contains a ``git commit`` invocation.

    Uses the shared quote-aware tokenizer so shell operators inside quoted
    strings are not treated as command separators.
    Skips ``env``, ``command``, ``sudo`` and other common shell wrappers,
    and normalises the executable name (basename, strip ``.exe``).
    """
    tokens = tokenize_command(command.strip(), shell)
    segments = _command_segments(tokens)

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
    if _has_git_commit(ctx.command, ctx.tool_name):
        return CheckResult("ask", "git commit requires user approval")
    return None


# ---------------------------------------------------------------------------
# Checker registry
# ---------------------------------------------------------------------------

CHECKERS: list[Checker] = [
    check_blocked_files,
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
