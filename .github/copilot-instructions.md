# Copilot Instructions (Repository-Level)

This repository manages cross-platform dotfiles using **chezmoi** and **mise**.

## Architecture

- `home/` is the chezmoi source directory (`.chezmoiroot` points here)
- Files in `home/` map to `~/` on the target machine
- chezmoi naming conventions: `dot_` → `.`, `private_` → restricted permissions, `executable_` → +x, `.tmpl` → template
- `reference/` contains non-deployed files (e.g., Windows DSC, terminal themes)

## Templates

- Templates use Go template syntax (`{{ }}`)
- Platform detection variables are defined in `home/.chezmoi.toml.tmpl`:
  - `.chezmoi.os` — `linux`, `darwin`, `windows`
  - `.isWSL` — boolean, true on WSL environments
  - `.codespaces` — boolean, true in GitHub Codespaces
  - `.windowsUser` — Windows username (for WSL 1Password paths)
  - `.corpUser` — Corporate Git username

## Copilot Guard Hooks

- Single Python implementation at `home/private_dot_copilot/hooks/scripts/executable_copilot-guard.py`
- Executed via `uv run` (no system Python dependency)
- Config files: `blocked-files.txt` (deny patterns), `allowed-urls.txt` (URL allowlist)
- Fail-safe: any error results in deny

## Tool Management

- **mise** manages tool versions (`.mise.toml`)
- **uv** manages Python execution (installed via mise)
- No direct `python3`, `pip`, or `brew install python` — uv handles all Python needs
