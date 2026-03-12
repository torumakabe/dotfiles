# dotfiles

Cross-platform dotfiles managed by [chezmoi](https://www.chezmoi.io/) + [mise](https://mise.jdx.dev/).

## 対応環境

| 環境 | セットアップ | 注意点 |
|------|------------|--------|
| Linux / macOS | [クイックスタート → Linux / macOS / WSL](#linux--macos--wsl) | — |
| WSL | [クイックスタート → Linux / macOS / WSL](#linux--macos--wsl) | 1Password パスが Windows 側、初回 `windowsUser` 入力が必要 |
| GitHub Codespaces | [クイックスタート → Codespaces](#github-codespaces) | `corpUser` 未設定 |
| Dev Container (ローカル) | [クイックスタート → Dev Container](#dev-container-ローカル) | 初回 `mise install --yes` を手動実行 |
| Windows | [クイックスタート → Windows](#windows) | — |

## クイックスタート

### Linux / macOS / WSL

任意のディレクトリで実行できる（chezmoi がリポジトリのクローンと配置を自動で行う）:

```bash
sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply torumakabe
```

初回実行時にプラットフォーム検出と変数の入力プロンプトが表示される:

- **Windows username** (WSL のみ): 1Password の WSL 連携パスに使用
- **Corp username** (任意): 所属企業での Git ユーザー名。gitconfig に使用

### GitHub Codespaces

自動適用される。GitHub の設定で dotfiles リポジトリとして登録するだけでよい。
参考: [Codespaces docs](https://docs.github.com/en/codespaces/setting-your-user-preferences/personalizing-github-codespaces-for-your-account#dotfiles)

**制限事項:**

- 非対話環境のため `corpUser` / `windowsUser` のプロンプトはスキップされ、空文字になる（`.gitconfig-corp` は適用されない）

### Dev Container (ローカル)

任意のリポジトリの Dev Container で dotfiles を適用するケース。VS Code の設定で dotfiles リポジトリを指定すると、コンテナ作成時に `install.sh` が自動実行される。
参考: [Personalizing with dotfile repositories](https://code.visualstudio.com/docs/devcontainers/containers#_personalizing-with-dotfile-repositories)

1. VS Code の Settings → **Dotfiles** で以下を設定:
   - **Repository**: `torumakabe/dotfiles`
   - **Install Command**: `install.sh`（デフォルト、変更不要）
2. Dev Container を作成すると `install.sh` → `chezmoi init --apply` が自動実行される
3. コンテナ起動後にターミナルから手動で実行:
   ```bash
   mise install --yes
   ```

**制限事項:**

- `mise install` はコンテナ作成時にスキップされる（GitHub API トークンが利用できず、レート制限に抵触する可能性が高いため）。コンテナ起動後に手動実行が必要
- Azure CLI 等の追加ツール（`run_once_after_30-install-tools.sh`）もスキップされる。ベースイメージまたは Dev Container Feature で導入される想定
- 非対話環境のため `corpUser` / `windowsUser` のプロンプトはスキップされ、空文字になる

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
   chezmoi が `~/PowerShell_profile.ps1` を配置する。`$PROFILE` は OneDrive 配下になることもあり chezmoi の管理外のため、ローダー（1行の dot-source）で橋渡しする。

## 日常操作

### chezmoi で管理するもの・しないもの

| 分類 | 例 | 編集方法 |
|------|----|----------|
| **chezmoi 管理** | `.gitconfig`, `.zshrc`, `.config/mise/config.toml`, `.copilot/` | `chezmoi edit` でソースを編集 → `chezmoi apply`（※1） |
| **mise 管理** | Go, Node, Terraform 等のバージョン | `.config/mise/config.toml` を `chezmoi edit` で編集 → `mise install` |
| **手動管理** | `reference/windows/` 配下 (DSC, Terminal テーマ) | 直接編集し git commit。chezmoi は関与しない |
| **リポジトリメタ情報** | `.github/copilot-instructions.md`, `README.md` | 直接編集し git commit |

**重要**: chezmoi 管理下のファイル（`~/.gitconfig` 等）を直接編集しても、次回の `chezmoi apply` で上書きされる。永続化するには必ず `chezmoi edit` でソース側を変更すること。

> **※1**: `~/.copilot/mcp-config.json` は例外的に、Copilot CLI の `/mcp add` コマンドでローカル側が変更される場合がある。変更後は `chezmoi re-add ~/.copilot/mcp-config.json` でソースに反映すること。

### パッケージの管理

| 環境 | 管理ツール | 対象 |
|------|-----------|------|
| Linux / WSL | `apt` + `mise` | apt: OS パッケージ、mise: 開発ツール |
| macOS | `brew` + `mise` | brew: OS パッケージ・GUI アプリ、mise: 開発ツール |
| Codespaces / Dev Container | ベースイメージ / Feature + `mise` | ベースイメージ・Feature: 主要ツール同梱、mise: 開発ツール |
| Windows | `winget` (DSC) + `mise` | winget: GUI アプリ・OS ツール、mise: 開発ツール |
| 全環境共通 | `uv` | Python スクリプト実行（システム Python 不要） |

### chezmoi コマンドリファレンス

| コマンド | 参照先 | 用途 |
|----------|--------|------|
| `chezmoi init <repo>` | **リモート** | 初回セットアップ（リポジトリをクローン）、構成テンプレート変更時の再初期化 |
| `chezmoi update` | **リモート** | `git pull` + `apply` を一括実行 |
| `chezmoi apply` | ローカル | ソース → ホームに反映 |
| `chezmoi diff` | ローカル | ソースとホームの差分表示 |
| `chezmoi cat <file>` | ローカル | テンプレート展開結果の確認 |
| `chezmoi edit <file>` | ローカル | ソースを編集（エディタが開く） |
| `chezmoi add <file>` | ローカル | ホームの変更をソースに取り込み |

リモート参照は `init` と `update` のみ。全コマンドは任意のディレクトリで実行できる。

変更をリモートに反映するには、chezmoi のソースディレクトリ（`chezmoi source-path` で確認可能）で `git commit` + `git push` する。ローカルでテンプレートの変更を試すだけなら push 不要で `chezmoi apply` で即反映できる。

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

### mise 管理ツールの更新

日常的なツールの更新は `mise upgrade` で行う。config.toml は `latest` 指定のため変更されず、**lockfile が実際のバージョンを固定する**。`mise upgrade` は lockfile も自動更新する。

```bash
# 全ツールを最新バージョンに更新（lockfile も自動更新される）
mise upgrade

# lockfile を chezmoi に反映してコミット・プッシュ
chezmoi re-add ~/.config/mise/mise.lock
cd $(chezmoi source-path)/..
git add -A && git commit -m "chore: upgrade mise tools"
git push
```

> **補足**: `mise upgrade` は lockfile の全プラットフォーム分のエントリを維持する。ただし新しいツールを追加した場合は `mise lock --platform linux-x64,linux-arm64,macos-arm64,windows-x64` で全プラットフォーム分を生成すること。他の端末で `chezmoi update` すると lockfile 経由で同じバージョンがインストールされる。

### ツールの追加・削除

新しいツールの追加や既存ツールの削除は config.toml を編集する。

```bash
# config.toml を編集
chezmoi edit ~/.config/mise/config.toml

# インストール
mise install

# 全プラットフォーム分の lockfile を生成して反映
mise lock --platform linux-x64,linux-arm64,macos-arm64,windows-x64
chezmoi re-add ~/.config/mise/config.toml
chezmoi re-add ~/.config/mise/mise.lock
```

### mise lockfile について

`mise.lock` は各ツールのダウンロード URL とチェックサムを事前に解決したファイル。これにより `mise install` 時の GitHub API 呼び出しが不要になり、レート制限を回避できる。`GITHUB_TOKEN` の環境変数設定も不要。

**注意事項:**

- lockfile が存在する環境では `mise install` に `--locked` が自動付与される（`run_once_after_20`）
- `--locked` 時は lockfile にないツールがエラーになる。ツールの追加・更新後は必ず lockfile を再生成してからコミットすること
- `mise upgrade` と `mise lock` は GitHub API を呼ぶため、レート制限を受ける場合がある。その際は一時的に `GITHUB_TOKEN=$(gh auth token) mise upgrade` で実行する
- lockfile がない環境（初回セットアップ等）では従来どおり GitHub API 経由でインストールされる

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
| `hooks/hooks.json` | preToolUse フック定義 | chezmoi |
| `hooks/scripts/copilot-guard.py` | セキュリティガード（ファイル・URL 制限） | chezmoi |
| `hooks/scripts/uv-enforcer.py` | python/pip 直接実行をブロックし uv 経由を強制 | chezmoi |
| `hooks/blocked-files.txt` | ブロック対象ファイルパターン | chezmoi |
| `hooks/allowed-urls.txt` | URL 許可リスト | chezmoi |
| `skills/` | エージェントスキル | chezmoi（上流更新時は再取得して `re-add`） |
| `installed-plugins/` | プラグイン | `/plugin install` で管理（chezmoi 対象外） |

### プラグインの管理

プラグインは `/plugin` コマンドで管理する。chezmoi の管理外。

```
# マーケットプレイスからプラグインを追加
/plugin marketplace add <publisher>/<plugin>
/plugin install <name>@<plugin>

# 更新
/plugin update <name>@<plugin>
```

例: [Azure Skills Plugin](https://github.com/microsoft/azure-skills) を導入すると、Azure スキル（20+）、Azure MCP Server、Foundry MCP がまとめてインストールされる。

```
/plugin marketplace add microsoft/azure-skills
/plugin install azure@azure-skills
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

### フックのテスト

フックは stdin に JSON を受け取り、stdout に許可/拒否の JSON を返す。手動テスト:

```bash
# copilot-guard: ファイル・URL アクセス制御
echo '{"toolName":"edit","toolArgs":{"path":".env"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py
# → {"permissionDecision": "deny", ...}

# uv-enforcer: python/pip 直接実行のブロック
echo '{"toolName":"bash","toolArgs":{"command":"python script.py"}}' | uv run ~/.copilot/hooks/scripts/uv-enforcer.py
# → {"permissionDecision": "deny", ...}
```

## ディレクトリ構造

```
home/                          ← chezmoi source (.chezmoiroot で指定)
├── .chezmoi.toml.tmpl         ← プラットフォーム検出・変数定義
├── .chezmoiignore             ← OS 別にファイルをスキップ
├── .chezmoiremove             ← レガシーファイル自動削除
├── dot_gitconfig.tmpl         ← ベース gitconfig (includeIf で分岐)
├── dot_gitconfig-linux.tmpl   ← Linux/WSL 共通 (内部で WSL 分岐)
├── dot_gitconfig-mac.tmpl     ← macOS 用
├── dot_gitconfig-windows.tmpl ← Windows 用
├── dot_gitconfig-corp.tmpl    ← 所属企業リポジトリ用
├── dot_zshrc.tmpl             ← シェル設定
├── dot_config/
│   └── mise/
│       ├── config.toml.tmpl   ← mise ツールバージョン定義
│       └── mise.lock          ← mise lockfile (mise lock で生成)
├── PowerShell_profile.ps1.tmpl ← Windows PowerShell Profile (mise activate 含む)
├── private_dot_copilot/       ← ~/.copilot/ に配置
│   ├── copilot-instructions.md
│   ├── mcp-config.json        ← MCP サーバー設定 (/mcp add 後は re-add)
│   ├── hooks/
│   │   ├── hooks.json         ← preToolUse フック定義
│   │   ├── blocked-files.txt  ← ブロックパターン
│   │   ├── allowed-urls.txt   ← URL 許可リスト
│   │   └── scripts/
│   │       ├── copilot-guard.py  ← セキュリティガード
│   │       └── uv-enforcer.py   ← python/pip 直接実行ブロック
│   └── skills/                ← エージェントスキル
├── run_once_before_*          ← パッケージ・mise インストール
└── run_once_after_*           ← シェル・ツールセットアップ
reference/windows/             ← デプロイしない参照ファイル
├── configuration.dsc.yaml     ← WinGet DSC (手動実行)
└── winterm-settings.json      ← Windows Terminal テーマ
.github/
└── copilot-instructions.md    ← リポジトリレベル Copilot 指示
```

`.chezmoiremove` は `chezmoi apply` 時にホームディレクトリから不要になったファイルを自動削除する。現在は `~/.mise.toml`（`~/.config/mise/config.toml` への移行に伴うレガシーファイル）を対象としている。

## 主要な決定事項

- **chezmoi** が設定ファイルの配置・テンプレート化・プラットフォーム分岐を担当
- **mise** が全プラットフォームでツールバージョンを管理 (`.config/mise/config.toml`)
- **uv** が Python 実行を管理 — システム Python のインストールは不要
- **Git includeIf** パターンを維持し、プラットフォーム別 gitconfig を自動読み込み
- **Copilot Guard** フック: bash + PowerShell の二重実装を Python 単一スクリプトに統一
- **uv Enforcer** フック: Copilot エージェントの python/pip 直接実行をブロックし uv 経由を強制
- **SAML SSO ワークアラウンド**: Codespaces の `mise install` で SAML SSO 要求による 403 を回避するため、失敗したツールを認証なしで自動リトライ
- **mise lockfile**: ダウンロード URL とチェックサムを事前解決し、GitHub API レート制限を回避。`GITHUB_TOKEN` 環境変数が不要になり、エージェントへの機密情報露出リスクも低減
- **Windows**: chezmoi で設定、DSC で GUI アプリ、mise でツール（段階的導入）

## プラットフォーム検出

| 変数名 | 説明 |
|--------|------|
| `.chezmoi.os` | `linux`, `darwin`, `windows` |
| `.isWSL` | WSL 環境の検出 |
| `.codespaces` | GitHub Codespaces |
| `.devcontainer` | Dev Container |
| `.windowsUser` | Windows ユーザー名 (WSL 1Password パス) |
| `.corpUser` | 所属企業での Git ユーザー名 |

## トラブルシューティング

### `warning: config file template has changed`

`.chezmoi.toml.tmpl` が更新された場合に表示される。設定を再生成する:

```bash
chezmoi init torumakabe
```

> **注意**: リポジトリ名を省略すると、ソースディレクトリが空になり `chezmoi update` が動かなくなる。必ず `torumakabe` を指定すること。

### `mise install` が部分失敗する

GitHub API レート制限やネットワーク障害でツールの一部がインストールされない場合がある。

lockfile（`~/.config/mise/mise.lock`）が存在する環境では GitHub API を呼ばないため、レート制限は発生しない。lockfile がない場合や `mise upgrade` 後に lockfile が古い場合は以下で対処する。

```bash
# 未インストールのツールを確認
mise ls --missing

# リトライ
mise install

# lockfile を更新して次回以降のレート制限を回避
mise lock --platform linux-x64,linux-arm64,macos-arm64,windows-x64
chezmoi re-add ~/.config/mise/mise.lock
```

### `run_once_` スクリプトが sudo を要求して停止する

Codespaces 以外の環境では、パッケージインストールに sudo が必要。
パスワードを入力するか、sudoers を設定する。

### Dev Container で mise ツールが入っていない

コンテナ作成時に `mise install` は自動スキップされる（GitHub API トークン不在のため）。
コンテナ起動後にターミナルから手動実行する:

```bash
mise install --yes
```
