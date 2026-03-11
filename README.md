# dotfiles

Cross-platform dotfiles managed by [chezmoi](https://www.chezmoi.io/) + [mise](https://mise.jdx.dev/).

## Quick Start

### Linux / macOS / WSL

任意のディレクトリで実行できる（chezmoi がリポジトリのクローンと配置を自動で行う）:

```bash
sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply torumakabe
```

初回実行時にプラットフォーム検出と変数の入力プロンプトが表示される:

- **Windows username** (WSL のみ): 1Password の WSL 連携パスに使用
- **Corp username** (任意): 社内リポジトリ用 gitconfig に使用

### GitHub Codespaces

自動適用される。GitHub の設定で dotfiles リポジトリとして登録するだけでよい。
参考: [Codespaces docs](https://docs.github.com/en/codespaces/setting-your-user-preferences/personalizing-github-codespaces-for-your-account#dotfiles)

**制限事項:**

- 非対話環境のため `corpUser` / `windowsUser` のプロンプトはスキップされ、空文字になる（`.gitconfig-corp` は適用されない）
- `mise install` がベースイメージの GitHub API レート制限で部分失敗する場合がある。ターミナルにリカバリ手順が表示される

### Windows

1. chezmoi インストール: `winget install twpayne.chezmoi`
2. 設定適用: `chezmoi init --apply torumakabe`
3. GUI アプリ: `winget configure -f "$(chezmoi source-path)\..\reference\windows\configuration.dsc.yaml"`
4. PowerShell Profile のローダー設定（初回のみ）:
   ```powershell
   # $PROFILE（OneDrive 配下）から chezmoi 管理のファイルを読み込む
   if (!(Test-Path $PROFILE)) { New-Item -Path $PROFILE -Type File -Force }
   $line = '. "$env:USERPROFILE\PowerShell_profile.ps1"'
   if (!(Select-String -Path $PROFILE -SimpleMatch $line -Quiet)) {
       Add-Content -Path $PROFILE -Value $line
   }
   ```
   chezmoi が `~/PowerShell_profile.ps1` を配置する。`$PROFILE` は OneDrive 配下で chezmoi の管理外のため、ローダー（1行の dot-source）で橋渡しする。

## Day-to-Day Operations

### chezmoi で管理するもの・しないもの

| 分類 | 例 | 編集方法 |
|------|----|----------|
| **chezmoi 管理** | `.gitconfig`, `.zshrc`, `.mise.toml`, `.copilot/` | `chezmoi edit` でソースを編集 → `chezmoi apply`（※1） |
| **mise 管理** | Go, Node, Terraform 等のバージョン | `.mise.toml` を `chezmoi edit` で編集 → `mise install` |
| **手動管理** | `reference/windows/` 配下 (DSC, Terminal テーマ) | 直接編集し git commit。chezmoi は関与しない |
| **リポジトリ設定** | `.github/copilot-instructions.md`, `README.md` | 直接編集し git commit |

**重要**: chezmoi 管理下のファイル（`~/.gitconfig` 等）を直接編集しても、次回の `chezmoi apply` で上書きされる。永続化するには必ず `chezmoi edit` でソース側を変更すること。

> **※1**: `~/.copilot/mcp-config.json` は例外的に、Copilot CLI の `/mcp add` コマンドでローカル側が変更される場合がある。変更後は `chezmoi re-add ~/.copilot/mcp-config.json` でソースに反映すること。

### パッケージの管理

| 環境 | パッケージマネージャ | 対象 |
|------|---------------------|------|
| Linux / WSL | `apt` + `mise` | apt: OS パッケージ、mise: 開発ツール |
| macOS | `brew` + `mise` | brew: OS パッケージ・GUI アプリ、mise: 開発ツール |
| Windows | `winget` (DSC) + `mise` | winget: GUI アプリ・OS ツール、mise: 開発ツール |
| 全環境共通 | `uv` | Python スクリプト実行（システム Python 不要） |

### chezmoi コマンドリファレンス

| コマンド | 参照先 | 用途 |
|----------|--------|------|
| `chezmoi init <repo>` | **リモート** | 初回セットアップ（リポジトリをクローン） |
| `chezmoi update` | **リモート** | `git pull` + `apply` を一括実行 |
| `chezmoi apply` | ローカル | ソース → ホームに反映 |
| `chezmoi diff` | ローカル | ソースとホームの差分表示 |
| `chezmoi cat <file>` | ローカル | テンプレート展開結果の確認 |
| `chezmoi edit <file>` | ローカル | ソースを編集（エディタが開く） |
| `chezmoi add <file>` | ローカル | ホームの変更をソースに取り込み |

リモート参照は `init` と `update` のみ。テンプレートの変更を試すだけなら push 不要で `chezmoi apply` で即反映できる。全コマンドは任意のディレクトリで実行できる。

### 設定ファイルの編集

```bash
# ソースを直接編集（エディタが開く）
chezmoi edit ~/.zshrc

# または、リポジトリ内のソースを直接編集してから適用
cd $(chezmoi source-path)/..    # ~/dotfiles 相当に移動
vim home/dot_zshrc.tmpl
chezmoi apply
```

### リモートの変更を取り込む

```bash
chezmoi update
```

これは `git pull` + `chezmoi apply` を一括で行う。

### 変更の確認（dry-run）

```bash
# 適用前の差分を確認
chezmoi diff

# 特定ファイルの生成結果を確認
chezmoi cat ~/.gitconfig
```

### 新しいファイルを chezmoi 管理下に追加

```bash
chezmoi add ~/.some-config
```

### ツールバージョンの更新

```bash
# mise.toml を編集してバージョンを変更
chezmoi edit ~/.mise.toml

# ツールをインストール
mise install
```

### run_once_ スクリプトの再実行

chezmoi の `run_once_` スクリプトはデフォルトで1回しか実行されない。
再実行が必要な場合:

```bash
# 状態をリセットして再実行
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

## GitHub Copilot CLI

chezmoi は `~/.copilot/` 配下の以下のファイルを管理する。プラグインはプラグインマネージャが管理するため chezmoi の対象外。

| ファイル | 用途 | 管理方法 |
|---------|------|----------|
| `copilot-instructions.md` | ユーザーレベルのカスタム指示 | chezmoi |
| `mcp-config.json` | MCP サーバー設定 | chezmoi（`/mcp add` 後は `re-add`） |
| `hooks/` | preToolUse ガードフック | chezmoi |
| `skills/` | エージェントスキル | chezmoi（上流更新時は再取得して `re-add`） |
| `installed-plugins/` | プラグイン | `/plugin install` で管理（chezmoi 対象外） |

### プラグインのセットアップ（初回のみ）

[Azure Skills Plugin](https://github.com/microsoft/azure-skills) を導入すると、Azure スキル（20+）、Azure MCP Server、Foundry MCP がまとめてインストールされる。

```
/plugin marketplace add microsoft/azure-skills
/plugin install azure@azure-skills
```

更新:

```
/plugin update azure@azure-skills
```

> **前提**: Node.js 18+、Azure CLI (`az login`)、Azure Developer CLI (`azd auth login`) が必要。

### スキルの管理

ユーザーレベルのスキル（`~/.copilot/skills/`）は chezmoi で管理する。新しいスキルの追加・更新手順:

```bash
# 新しいスキルを追加（一時ディレクトリに取得して chezmoi に取り込む）
npx skills add -g <owner>/<repo>/<path>
chezmoi re-add ~/.copilot/skills/<skill-name>

# 上流の更新を取り込む
npx skills add -g <owner>/<repo>/<path>    # 上書きインストール
chezmoi re-add ~/.copilot/skills/<skill-name>
chezmoi diff                                # 変更内容を確認
```

現在インストール済みのスキル:

| スキル | ソース | 用途 |
|--------|--------|------|
| `microsoft-skill-creator` | [github/awesome-copilot](https://github.com/github/awesome-copilot) (MIT) | MS Learn MCP を使って Microsoft 技術のスキルを生成 |

### ガードフックのテスト

フックは stdin に JSON を受け取り、stdout に許可/拒否の JSON を返す。手動テスト:

```bash
echo '{"toolName":"bash","toolArgs":{"command":"ls"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py
# → {"permissionDecision": "allow"}

echo '{"toolName":"edit","toolArgs":{"path":".env"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py
# → deny
```

## Troubleshooting

### `warning: config file template has changed`

`.chezmoi.toml.tmpl` が更新された場合に表示される。設定を再生成する:

```bash
chezmoi init torumakabe
```

> **注意**: リポジトリ名を省略すると、ソースディレクトリが空になり `chezmoi update` が動かなくなる。必ず `torumakabe` を指定すること。

### `mise install` が部分失敗する

GitHub API レート制限やネットワーク障害でツールの一部がインストールされない場合がある。

```bash
# 未インストールのツールを確認
mise ls --missing

# リトライ
mise install
```

### `run_once_` スクリプトが sudo を要求して停止する

Codespaces 以外の環境では、パッケージインストールに sudo が必要。
パスワードを入力するか、sudoers を設定する。

## Architecture

```
home/                          ← chezmoi source (.chezmoiroot で指定)
├── .chezmoi.toml.tmpl         ← プラットフォーム検出・変数定義
├── .chezmoiignore             ← OS 別にファイルをスキップ
├── dot_gitconfig.tmpl         ← ベース gitconfig (includeIf で分岐)
├── dot_gitconfig-linux.tmpl   ← Linux/WSL 共通 (内部で WSL 分岐)
├── dot_gitconfig-mac.tmpl     ← macOS 用
├── dot_gitconfig-windows.tmpl ← Windows 用
├── dot_gitconfig-corp.tmpl    ← 社内リポジトリ用
├── dot_zshrc.tmpl             ← シェル設定
├── dot_mise.toml              ← ツールバージョン定義
├── PowerShell_profile.ps1.tmpl ← Windows PowerShell Profile (mise activate 含む)
├── private_dot_copilot/       ← ~/.copilot/ に配置
│   ├── copilot-instructions.md
│   ├── mcp-config.json        ← MCP サーバー設定 (/mcp add 後は re-add)
│   └── hooks/
│       ├── copilot-guard.json ← フック定義 (uv run)
│       ├── blocked-files.txt  ← ブロックパターン
│       ├── allowed-urls.txt   ← URL 許可リスト
│       └── scripts/
│           └── copilot-guard.py  ← 統一ガードスクリプト
├── run_once_before_*          ← パッケージ・mise インストール
└── run_once_after_*           ← シェル・ツールセットアップ
reference/windows/             ← デプロイしない参照ファイル
├── configuration.dsc.yaml     ← WinGet DSC (手動実行)
└── winterm-settings.json      ← Windows Terminal テーマ
.github/
└── copilot-instructions.md    ← リポジトリレベル Copilot 指示
```

## Key Design Decisions

- **chezmoi** が設定ファイルの配置・テンプレート化・プラットフォーム分岐を担当
- **mise** が全プラットフォームでツールバージョンを管理 (`.mise.toml`)
- **uv** が Python 実行を管理 — システム Python のインストールは不要
- **Git includeIf** パターンを維持し、プラットフォーム別 gitconfig を自動読み込み
- **Copilot Guard** フック: bash + PowerShell の二重実装を Python 単一スクリプトに統一
- **Windows**: chezmoi で設定、DSC で GUI アプリ、mise でツール（段階的導入）

## Platform Detection

| Variable | Description |
|----------|-------------|
| `.chezmoi.os` | `linux`, `darwin`, `windows` |
| `.isWSL` | WSL 環境の検出 |
| `.codespaces` | GitHub Codespaces |
| `.devcontainer` | Dev Container |
| `.windowsUser` | Windows ユーザー名 (WSL 1Password パス) |
| `.corpUser` | 社内 Git ユーザー名 |
