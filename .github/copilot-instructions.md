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
- **パス区切り文字**: Windows のバックスラッシュ (`\`) と Unix のフォワードスラッシュ (`/`) の両方を扱う。比較前に `/` へ正規化すること。パターンファイルは `/` で記述する

## Tool Management

- **mise** manages tool versions (`.mise.toml`)
- **uv** manages Python execution (installed via mise)
- No direct `python3`, `pip`, or `brew install python` — uv handles all Python needs

### mise のプラットフォーム制約

- `home/dot_config/mise/config.toml.tmpl` は chezmoi テンプレートで、プラットフォーム非対応ツールを条件付きでスキップする
- **cargo-make**: linux/arm64 のプリビルドバイナリが未提供のためスキップ中（[sagiegurari/cargo-make#541](https://github.com/sagiegurari/cargo-make/issues/541)）
- **定期チェック**: このリポジトリの mise 設定を変更する際は、[cargo-make の最新リリース](https://github.com/sagiegurari/cargo-make/releases)に `aarch64-unknown-linux` バイナリが追加されていないか確認すること。追加されていれば条件分岐を削除して全プラットフォーム共通に戻す

### Dev container での mise install

- Dev container（非 Codespaces）ではコンテナ作成時に GitHub API トークンが利用できず、レート制限（60 req/hr）に抵触するため `mise install` をスキップする
- コンテナ作成後にターミナルから `mise install --yes` を手動実行する
- Codespaces では `GITHUB_TOKEN` が自動設定されるためスキップしない

## Windows DSC と mise の重複

- `reference/windows/configuration.dsc.yaml` には mise でも管理しているツール（Go, Node, Terraform 等）が含まれている
- これは mise の Windows 対応が安定途上のため、フォールバックとして残している
- mise でのインストール・バージョン管理が安定したツールから、DSC のエントリを段階的に削除する
- DSC に残すべきもの: GUI アプリ（PowerToys, DevToys 等）、mise 未対応ツール、OS レベルの設定（DeveloperMode）
