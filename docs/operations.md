# Operations Guide

`README.md` には日常的に使う操作だけを残し、このファイルには **このリポジトリ固有の運用** をまとめる。一般的な `chezmoi` / `mise` の使い方は各公式ドキュメントを参照。

## ツールの管理境界

| 環境 | 管理ツール | 主な対象 |
|------|-----------|----------|
| Linux / WSL | `apt` + `mise` | OS パッケージ、Azure CLI、開発ツール |
| macOS | `brew` + `mise` | OS パッケージ、GUI アプリ、Azure CLI、開発ツール |
| Codespaces / Dev Container | ベースイメージ / Feature + `mise` | コンテナ基盤側ツール、開発ツール |
| Windows | `winget` (DSC) + `mise` | GUI/CLI アプリ、Azure CLI、開発ツール |
| 全環境共通 | `uv` | Python スクリプト実行 |

`copilot-cli` は全 OS で mise 外で管理する。macOS は `brew`、Windows は `winget`、Linux は公式インストールスクリプト (`gh.io/copilot-install`) を使い、更新は `copilot update` で行う。

## 定期チェック対象の制約

`mise` 設定や導入元を見直すときは、次の制約がまだ残っているか確認する。

- **cargo-make**: linux/arm64 向け配布がない
- **edit**: macOS 向け配布がない
- **azure-dev**: mise `github:` バックエンドがバイナリ名を正規化しないため、全 OS で mise 外で管理。macOS は `brew`、Windows は `winget`、Linux は公式インストーラー (`install-azd.sh`) を使い、更新は `azd update` で行う
- **copilot-cli**: mise の `github:` バックエンドでは更新が遅れ、自己更新後のバージョン誤認が発生するため、全 OS で mise 外で管理。macOS は `brew`、Windows は `winget`、Linux は公式インストールスクリプト (`gh.io/copilot-install`) を使い、更新は `copilot update` で行う

解消されていれば、条件分岐や導入元のワークアラウンドを外せる。

## chezmoi での編集

通常は `chezmoi edit` を使う。テンプレート全体を見ながら編集したいときだけ、ソースディレクトリを直接触る。

```bash
chezmoi edit ~/.zshrc
chezmoi diff
chezmoi apply
```

```bash
cd "$(chezmoi source-path)/.."
vim home/dot_zshrc.tmpl
chezmoi apply
```

## mise の保守

### `mise-upgrade`

シェル関数 `mise-upgrade` が次を一括実行する。

1. `gh auth token` で一時トークンを取得
2. `mise upgrade` を実行
3. 既存 lockfile を削除し、`mise lock --global --platform ...` で再生成
4. `chezmoi re-add` でソースへ戻す
5. git commit + push

```bash
mise-upgrade
```

初期構築直後はシェル設定が未読込のことがある。必要なら bash / zsh では `source ~/.zshrc`、PowerShell では `. $PROFILE` を実行する。

### 手動で更新する場合

この repo では次の 2 点が重要である。

- `mise lock` は **`--global` が必須**
- lockfile 再生成時は **`--platform` を常に指定**

さらに `mise upgrade` 後は lockfile を削除してから再生成する。既存エントリだけが残り、新版が反映されないことがあるため。

```bash
GITHUB_TOKEN=$(gh auth token) mise upgrade
rm -f ~/.config/mise/mise.lock
GITHUB_TOKEN=$(gh auth token) mise lock --global --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
chezmoi re-add ~/.config/mise/mise.lock
cd "$(chezmoi source-path)/.." && git add -A && git commit -m "chore: upgrade mise tools" && git push
```

```powershell
$env:GITHUB_TOKEN = (gh auth token); mise upgrade; Remove-Item ~\.config\mise\mise.lock -ErrorAction SilentlyContinue; mise lock --global --platform "linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64"; $env:GITHUB_TOKEN = $null
chezmoi re-add ~\.config\mise\mise.lock
cd (Join-Path (chezmoi source-path) ".."); git add -A; git commit -m "chore: upgrade mise tools"; git push
```

### ツールの追加・削除

```bash
chezmoi edit ~/.config/mise/config.toml
GITHUB_TOKEN=$(gh auth token) mise install
GITHUB_TOKEN=$(gh auth token) mise lock --global --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
chezmoi re-add ~/.config/mise/config.toml
chezmoi re-add ~/.config/mise/mise.lock
```

PowerShell では `$env:GITHUB_TOKEN = (gh auth token); <command>; $env:GITHUB_TOKEN = $null` で囲む。`--platform` の値は必ずクォートする。

### lockfile の再構築

次のときは lockfile を削除してから再生成する。

- 新しいプラットフォームの端末を使い始めた
- 不要なプラットフォームのエントリを除去したい
- lockfile が壊れた

```bash
rm ~/.config/mise/mise.lock
GITHUB_TOKEN=$(gh auth token) mise lock --global --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
chezmoi re-add ~/.config/mise/mise.lock
```

この repo で lockfile を更新対象にしているのは次の 5 プラットフォームである。

- `linux-x64`
- `linux-arm64`
- `macos-arm64`
- `windows-x64`
- `windows-arm64`

## GitHub API と `GITHUB_TOKEN`

`mise` は GitHub API を使ってダウンロード情報を解決する。未認証だとレート制限に当たりやすい。

```bash
gh auth login
GITHUB_TOKEN=$(gh auth token) mise install
```

```powershell
gh auth login
$env:GITHUB_TOKEN = (gh auth token); mise install; $env:GITHUB_TOKEN = $null
```

`GITHUB_TOKEN` を `.zshrc` や `$PROFILE` に常駐させないこと。

## 既知のワークアラウンド

- **Azure CLI SyntaxWarning**: `dot_zshrc.tmpl` の `az()` ラッパーで回避している。上流修正が入ったら削除を再検討する

## Bootstrap / shell pin の更新

初期セットアップ系スクリプトは、上流の最新版をその場で実行せず、リリース番号や SHA256 を pin している。更新時は **バージョン更新 → 公式チェックサム確認 → スクリプト反映** の順で行う。

- `install.sh`: `CHEZMOI_VERSION` と対応する SHA256
- `home/run_once_before_20-install-mise.sh.tmpl`: `MISE_VERSION` と対応する SHA256
- `home/run_once_after_10-setup-shell.sh.tmpl`: `OH_MY_ZSH_COMMIT`, `ZSH_COMPLETIONS_TAG`

最低限の確認:

```bash
shellcheck install.sh
sed '/^{{/d' home/run_once_before_20-install-mise.sh.tmpl | bash -n
sed '/^{{/d' home/run_once_after_10-setup-shell.sh.tmpl | bash -n
```

## git pre-commit フック

この repo では、dotfiles として配布するグローバル `pre-commit` フックを使う。`gitleaks` で staged 変更を検査したあと、必要なら各リポジトリの `.git/hooks/pre-commit` へ委譲する。

有効化確認:

```bash
git config --global core.hooksPath
```

期待値は `~/.config/git/hooks`。

フック自体を更新したら通常どおり反映する。

```bash
chezmoi edit ~/.config/git/hooks/pre-commit
chezmoi diff
chezmoi apply
```

## `run_once_*` の再実行

```bash
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

実行順や依存関係は [`docs/architecture.md`](architecture.md#run_once_-スクリプトの実行順と依存関係) を参照。
