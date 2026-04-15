# Architecture Guide

README から分離した、構成と設計判断の詳細である。運用手順は [`docs/operations.md`](operations.md) を参照。

## ディレクトリ構造

```text
home/                           ← chezmoi source (.chezmoiroot で指定)
├── .chezmoi.toml.tmpl          ← 共通 flag・変数定義
├── .chezmoiignore              ← 条件付き除外
├── .chezmoiremove              ← 不要ファイルの削除
├── dot_gitconfig*.tmpl         ← Git 設定
├── dot_zshrc.tmpl              ← zsh 設定
├── dot_config/
│   ├── git/hooks/pre-commit    ← gitleaks + ローカルフック委譲
│   └── mise/
│       ├── config.toml.tmpl    ← ツール定義
│       └── mise.lock           ← lockfile
├── PowerShell_profile.ps1.tmpl ← PowerShell 設定
├── private_dot_copilot/        ← ~/.copilot/ に配置
│   ├── copilot-instructions.md
│   ├── mcp-config.json          ← 手動 MCP サーバー設定
│   ├── hooks/
│   │   ├── hooks.json
│   │   ├── blocked-files.txt
│   │   ├── ask-files.txt
│   │   ├── allowed-urls.txt
│   │   └── scripts/
│   └── skills/
├── run_once_before_*           ← パッケージ・mise 自体の導入
└── run_once_after_*            ← shell・追加ツールの設定
reference/windows/              ← 参照専用ファイル
└── configuration.dsc.yaml      ← WinGet DSC
```

`.chezmoiremove` は `chezmoi apply` 時に不要ファイルを自動削除する。現在は `~/.mise.toml` が対象。

## 主要な決定事項

- **設定の配布** は `chezmoi`
- **ツール版管理** は `mise`
- **Python 実行** は `uv`
- **Git 差分の分岐** は `includeIf`
- **コミット署名** は 1Password SSH エージェントを基本にし、コンテナ系環境では自動無効化
- **Copilot Guard / uv Enforcer** で危険な操作を抑止
- **postToolUse 監査ログ** で事後確認を可能にする
- **`copilot-cruise`** で Autopilot の既定値を安全寄りに固定する
- **gitleaks 付き pre-commit** で共通の secret scan を配布する

## Copilot Guard の設計

`copilot-guard.py` は `preToolUse` フックとして、ツール呼び出しを実行前に検査する。

### 役割

1. **秘匿ファイルへのアクセス拒否** — `blocked-files.txt`
2. **確認付きアクセス** — `ask-files.txt`
3. **機微な環境変数読み取りの拒否** — `printenv`, `$TOKEN`, `os.environ` など
4. **許可外 URL の拒否** — `allowed-urls.txt`

判定優先度は **deny > ask > allow**。

### パス判定

パス比較前に `\` を `/` へ正規化する。パターンファイルは `/` 前提で書く。

### チェック層

```text
preToolUse 入力
  ├─ ファイルアクセスチェック
  ├─ 環境変数アクセスチェック
  └─ URL 許可リストチェック
```

環境変数チェックは「明らかに危険な列挙や展開を止める」方針で、通常作業でよく使う変数は許可リストで除外する。

## git pre-commit フック

グローバル `pre-commit` フックは `~/.config/git/hooks/pre-commit` に配置し、`core.hooksPath` で有効化する。

処理は次の 2 段構えである。

1. `gitleaks git --pre-commit --staged --redact --verbose --no-banner`
2. 各リポジトリの `.git/hooks/pre-commit` があれば追加で実行

これにより、共通の secret scan を強制しつつローカルフックも共存できる。

## プラットフォーム検出

| 変数名 | 説明 |
|--------|------|
| `.chezmoi.os` | `linux`, `darwin`, `windows` |
| `.isLinux` / `.isMac` / `.isWindows` | `.chezmoi.os` から導出 |
| `.isWSL` | Linux かつ `kernel.osrelease` に `microsoft` を含む |
| `.codespaces` | GitHub Codespaces |
| `.devcontainer` | Dev Container |
| `.windowsUser` | Windows ユーザー名 |
| `.corpUser` | 企業用 Git ユーザー名 |

## Git `includeIf`

`home/dot_gitconfig.tmpl` ではベース設定を `~/.gitconfig` に置き、プラットフォーム差分だけを `includeIf` で切り替える。

- `gitdir:/home/` → Linux / WSL
- `gitdir:/Users/` → macOS
- `gitdir/i:C:/`, `gitdir/i:D:/` → Windows

WSL は Linux 側の設定を読みつつ、内部で `.isWSL` を使って 1Password 連携パスだけを切り替える。

## コミット署名

1Password の SSH エージェントによる SSH 署名を既定で有効化している。

| 環境 | `gpg.ssh.program` |
|------|-------------------|
| macOS | `/Applications/1Password.app/Contents/MacOS/op-ssh-sign` |
| Linux | `/opt/1Password/op-ssh-sign` |
| WSL | `/mnt/c/Users/<windowsUser>/.../op-ssh-sign-wsl.exe` |
| Windows | `C:/Users/<windowsUser>/.../op-ssh-sign.exe` |

Dev Container / Codespaces では 1Password SSH エージェントを前提にできないため、`commit.gpgsign = false` に切り替える。

## `run_once_*` スクリプトの実行順と依存関係

chezmoi は `run_once_before_*` → 通常ファイル適用 → `run_once_after_*` の順に処理し、同じフェーズ内では数字順で実行する。

| 順序 | スクリプト | 役割 | 依存前提 |
|------|-----------|------|----------|
| 1 | `run_once_before_10-install-packages.sh` | OS パッケージ導入 | 後続で `git` / `zsh` を使える |
| 2 | `run_once_before_20-install-mise.sh` | `mise` 自体を導入 | 後続で `mise` が存在する |
| 3 | `run_once_after_10-setup-shell.sh` | shell 設定 | `git` / `zsh` は導入済み |
| 4 | `run_once_after_20-mise-install.sh` | `config.toml` / `mise.lock` を使ってツール導入 | dotfiles 配置後に動く |
| 5 | `run_once_after_30-install-tools.sh` | 追加ツール導入 | `mise install` 済み |

変更時は、`mise` 設定が配置される前に `mise install` しないことと、Codespaces / Dev Container の分岐を壊さないことを優先して確認する。
