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

### Windows

1. chezmoi インストール: `winget install twpayne.chezmoi`
2. 設定適用: `chezmoi init --apply torumakabe`
3. GUI アプリ: `winget configure -f reference/windows/configuration.dsc.yaml`

## Day-to-Day Operations

### chezmoi で管理するもの・しないもの

| 分類 | 例 | 編集方法 |
|------|----|----------|
| **chezmoi 管理** | `.gitconfig`, `.zshrc`, `.mise.toml`, `.copilot/` | `chezmoi edit` でソースを編集 → `chezmoi apply` |
| **mise 管理** | Go, Node, Terraform 等のバージョン | `.mise.toml` を `chezmoi edit` で編集 → `mise install` |
| **手動管理** | `reference/windows/` 配下 (DSC, Terminal テーマ) | 直接編集し git commit。chezmoi は関与しない |
| **リポジトリ設定** | `.github/copilot-instructions.md`, `README.md` | 直接編集し git commit |

**重要**: chezmoi 管理下のファイル（`~/.gitconfig` 等）を直接編集しても、次回の `chezmoi apply` で上書きされる。永続化するには必ず `chezmoi edit` でソース側を変更すること。

### パッケージの管理

| 環境 | パッケージマネージャ | 対象 |
|------|---------------------|------|
| Linux / WSL | `apt` + `mise` | apt: OS パッケージ、mise: 開発ツール |
| macOS | `brew` + `mise` | brew: OS パッケージ・GUI アプリ、mise: 開発ツール |
| Windows | `winget` (DSC) + `mise` | winget: GUI アプリ・OS ツール、mise: 開発ツール |
| 全環境共通 | `uv` | Python スクリプト実行（システム Python 不要） |

以下のコマンドは全て任意のディレクトリで実行できる（chezmoi がソースの場所を管理している）。

### 設定ファイルの編集

dotfiles を変更したい場合、chezmoi のソースを編集してから適用する:

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

### GitHub Copilot CLI フックスクリプトのテスト

フックは stdin に JSON を受け取り、stdout に許可/拒否の JSON を返す。手動テスト:

```bash
echo '{"toolName":"bash","toolArgs":{"command":"ls"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py
# → {"permissionDecision": "allow"}

echo '{"toolName":"edit","toolArgs":{"path":".env"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py
# → deny
```

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
├── private_dot_copilot/       ← ~/.copilot/ に配置
│   ├── copilot-instructions.md
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
