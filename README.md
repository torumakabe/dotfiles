# dotfiles

Cross-platform dotfiles managed by [chezmoi](https://www.chezmoi.io/) + [mise](https://mise.jdx.dev/).

## Quick Start

### Linux / macOS / WSL

```bash
sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply torumakabe
```

### GitHub Codespaces

Automatically applied when this repository is set as your dotfiles repository.
See [Codespaces docs](https://docs.github.com/en/codespaces/setting-your-user-preferences/personalizing-github-codespaces-for-your-account#dotfiles).

### Windows

1. Install chezmoi: `winget install twpayne.chezmoi`
2. Apply configs: `chezmoi init --apply torumakabe`
3. Run DSC for GUI apps: `winget configure -f reference/windows/configuration.dsc.yaml`

## Architecture

```
home/                          ← chezmoi source (maps to ~/)
├── .chezmoi.toml.tmpl         ← Platform detection & user variables
├── dot_gitconfig*.tmpl        ← Git config templates (includeIf pattern)
├── dot_zshrc.tmpl             ← Shell config
├── dot_mise.toml              ← Tool versions (mise)
├── private_dot_copilot/       ← Copilot hooks & instructions
│   ├── hooks/scripts/
│   │   └── copilot-guard.py   ← Unified guard hook (uv run)
│   └── copilot-instructions.md
├── run_once_before_*          ← System packages, mise install
└── run_once_after_*           ← Shell setup, tools install
reference/windows/             ← Non-deployed (manual apply)
├── configuration.dsc.yaml     ← WinGet DSC
└── winterm-settings.json      ← Windows Terminal theme
```

## Key Design Decisions

- **chezmoi** handles config file deployment, templating, and platform branching
- **mise** manages tool versions across all platforms (`.mise.toml`)
- **uv** manages Python execution — no system Python installs anywhere
- **Git includeIf** pattern preserved for platform-specific gitconfig
- **Copilot Guard** hook: single Python script replaces bash + PowerShell dual implementation
- **Windows**: chezmoi for configs, DSC for GUI apps, mise for tools (staged adoption)

## Platform Detection

| Variable | Description |
|----------|-------------|
| `.chezmoi.os` | `linux`, `darwin`, `windows` |
| `.isWSL` | WSL environment detection |
| `.codespaces` | GitHub Codespaces |
| `.windowsUser` | Windows username (WSL 1Password paths) |
| `.corpUser` | Corporate Git username |
