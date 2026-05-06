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

## 定期チェック対象の制約

`mise` 設定や導入元を見直すときに、次の制約が残っているか確認する。解消されていれば条件分岐やワークアラウンドを外せる。

- **cargo-make**: linux/arm64 向け配布なし
- **azure-dev**: mise `github:` バックエンドがバイナリ名を正規化しないため mise 外管理（macOS: `brew` / Windows: `winget` / Linux: `install-azd.sh`、更新は `azd update`）
- **copilot-cli**: mise の `github:` バックエンドで更新遅延・バージョン誤認が起きるため mise 外管理（macOS: `brew` / Windows: `winget` / Linux: `gh.io/copilot-install`、更新は `copilot update`）
- **edit**（Microsoft Edit）: Windows のみ winget/DSC で管理（`reference/windows/configuration.dsc.yaml`）。macOS / Linux では未使用

## chezmoi での編集

通常は `chezmoi edit`。テンプレート全体を見ながら編集したいときだけソースを直接触る。

```bash
chezmoi edit ~/.zshrc   # または: vim "$(chezmoi source-path)/../home/dot_zshrc.tmpl"
chezmoi diff && chezmoi apply
```

## mise の保守

### `mise-upgrade`

シェル関数 `mise-upgrade` が次を一括実行する。

1. `gh auth token` で一時トークンを取得
2. `mise upgrade`
3. 既存 lockfile を削除し、`mise lock --global --platform ...` で再生成
4. `chezmoi re-add`
5. git commit + push

```bash
mise-upgrade
```

### 手動操作の重要ルール

- `mise lock` は **`--global` が必須**（省略するとプロジェクト設定のみ対象になる）
- lockfile 再生成時は **`--platform` を常に指定**
- `mise upgrade` 後は lockfile を一度削除してから再生成する（既存エントリが残り新版が反映されないため）
- PowerShell では `$env:GITHUB_TOKEN = (gh auth token); <cmd>; $env:GITHUB_TOKEN = $null` でトークンを渡し、`--platform` の値はクォートする

対象プラットフォーム: `linux-x64`, `linux-arm64`, `macos-arm64`, `windows-x64`, `windows-arm64`

### 典型コマンド

```bash
# mise upgrade + lockfile 再生成
GITHUB_TOKEN=$(gh auth token) mise upgrade
rm -f ~/.config/mise/mise.lock
GITHUB_TOKEN=$(gh auth token) mise lock --global --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
chezmoi re-add ~/.config/mise/mise.lock

# ツール追加・削除
chezmoi edit ~/.config/mise/config.toml
GITHUB_TOKEN=$(gh auth token) mise install
GITHUB_TOKEN=$(gh auth token) mise lock --global --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
chezmoi re-add ~/.config/mise/config.toml ~/.config/mise/mise.lock
```

lockfile を削除して再生成したいケース: 新プラットフォーム追加、不要プラットフォーム除去、lockfile 破損。

## GitHub API と `GITHUB_TOKEN`

`mise` は GitHub API を使うため、未認証だとレート制限に当たりやすい。

```bash
gh auth login
GITHUB_TOKEN=$(gh auth token) mise install
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

グローバル pre-commit を `~/.config/git/hooks/pre-commit` に配置し、`gitleaks` で staged 変更を検査する。必要ならリポジトリローカルの `.git/hooks/pre-commit` に委譲する。

```bash
git config --global core.hooksPath   # 期待値: ~/.config/git/hooks
chezmoi edit ~/.config/git/hooks/pre-commit && chezmoi apply
```

## `run_once_*` の再実行

```bash
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

実行順は [`architecture.md`](architecture.md#run_once_-スクリプトの実行順) を参照。
