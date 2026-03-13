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

- **mise** manages tool versions (`config.toml`)
- **uv** manages Python execution (installed via mise)
- No direct `python3`, `pip`, or `brew install python` — uv handles all Python needs

### mise lockfile 設定

- `config.toml` で `lockfile = true` を設定。`mise install` / `mise upgrade` ともに lockfile（`mise.lock`）を自動更新する
- 他端末では `chezmoi update` で lockfile が同期され、lockfile の URL から直接ダウンロードする（API 不要、トークン不要）
- `mise upgrade` や `mise lock` 実行時はトークンを一時的に渡す:
  - bash: `GITHUB_TOKEN=$(gh auth token) mise upgrade`
  - PowerShell: `$env:GITHUB_TOKEN = (gh auth token); mise upgrade; $env:GITHUB_TOKEN = $null`
- `mise lock` は**常に `--platform` を指定する**。引数なしだと既定の 8 プラットフォーム（musl 含む）が対象になる:
  - bash: `mise lock --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64`
  - PowerShell: `mise lock --platform "linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64"`（カンマが配列演算子として解釈されるのを防ぐ）
- `GITHUB_TOKEN` を `.zshrc` 等の環境変数に常駐させないこと（エージェントへの機密情報露出を防ぐため）

### mise のプラットフォーム制約

- `home/dot_config/mise/config.toml.tmpl` は chezmoi テンプレートで、プラットフォーム非対応ツールを条件付きでスキップする
- **cargo-make**: linux/arm64 のプリビルドバイナリが未提供のためスキップ中（[sagiegurari/cargo-make#541](https://github.com/sagiegurari/cargo-make/issues/541)）
- **edit**: macOS 向けプリビルドバイナリが未提供のためスキップ中。[edit の最新リリース](https://github.com/microsoft/edit/releases)に macOS バイナリが追加されたら条件分岐を削除する
- **azure-dev**: [aqua レジストリ](https://github.com/aquaproj/aqua-registry/blob/main/pkgs/Azure/azure-dev/registry.yaml)の `supported_envs` が `[darwin, amd64]` のみで linux/arm64 未対応。`github:Azure/azure-dev` バックエンドで全プラットフォームに対応中。aqua レジストリに linux/arm64 が追加されたら `aqua:` に戻す
- **定期チェック**: このリポジトリの mise 設定を変更する際は、上記ツールのリリースページやレジストリでプラットフォーム対応状況を確認すること。対応されていれば条件分岐やバックエンド変更を元に戻す

### Dev container での mise install

- Dev container（非 Codespaces）ではコンテナ作成時に GitHub API トークンが利用できず、レート制限（60 req/hr）に抵触するため `mise install` をスキップする
- コンテナ作成後にターミナルから `mise install --yes` を手動実行する
- Codespaces では `GITHUB_TOKEN` が自動設定されるためスキップしない

## ワークアラウンド

- **Azure CLI SyntaxWarning**: `home/dot_zshrc.tmpl` に `az()` ラッパー関数があり、`PYTHONWARNINGS="ignore::SyntaxWarning"` で警告を抑制している。[Azure/azure-sdk-for-python#38618](https://github.com/Azure/azure-sdk-for-python/issues/38618) が解決されたらラッパーを削除する
- **定期チェック**: このリポジトリの Azure CLI 関連ファイルを変更する際は、上記 issue のステータスを確認すること。Close されていればラッパーを削除する

## Windows DSC と mise の役割分担

- CLI ツールのバージョン管理は mise に一本化済み
- `reference/windows/configuration.dsc.yaml` には mise で管理しないものだけを残す:
  - OS 設定（DeveloperMode）
  - GUI アプリ（PowerToys, DevToys, draw.io 等）
  - ブートストラップ（mise 自身, Git, PowerShell）
