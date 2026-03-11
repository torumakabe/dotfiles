# Copilot Instructions (User-Level)

## Language

- Respond in Japanese unless the context clearly requires English
- Code comments in Japanese for personal projects; English for OSS contributions

## General Preferences

- Prefer simplicity and readability over cleverness
- Use established tools and patterns; avoid reinventing the wheel
- Explain trade-offs when multiple approaches exist

## Shell Scripts

- Use `set -euo pipefail` in bash scripts
- Prefer POSIX-compatible syntax unless bash-specific features are needed
- Use `command -v` instead of `which` for command existence checks

## Python

- Target Python 3.9+ for broad compatibility
- Use type hints (PEP 484 / PEP 604 union syntax for 3.10+)
- Prefer standard library over external dependencies when practical
- Use PEP 723 inline metadata for single-file scripts run via `uv run`
- **Always use `uv` for Python execution and package management**
  - `uv run` for script execution (not `python3` / `python`)
  - `uv add` / `uv pip` for dependency management (not `pip` / `pip3`)
  - `uv venv` for virtual environments (not `python -m venv`)

## Infrastructure / Cloud

- Primary cloud: Azure
- IaC: Terraform (prefer over Bicep/ARM for multi-provider consistency)
- Container orchestration: Kubernetes (AKS)
- Prefer Azure CLI (`az`) over portal for automation

## Git

- Conventional Commits format for commit messages
- Sign commits with SSH keys (1Password managed)
