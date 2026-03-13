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

任意のディレクトリでリポジトリを clone してから実行する。`install.sh` は検証済みの `chezmoi` リリースだけを展開し、その後 `chezmoi` がリポジトリのクローンと配置を自動で行う:

```bash
git clone https://github.com/torumakabe/dotfiles.git ~/dotfiles
cd ~/dotfiles
./install.sh
```

初回実行時にプラットフォーム検出と変数の入力プロンプトが表示される:

- **Windows username** (WSL のみ): 1Password の WSL 連携パスに使用
- **Corp username** (任意): 所属企業での Git ユーザー名。gitconfig に使用

`install.sh` の実行中に `mise install` がレート制限で一部失敗した場合は、[mise と GitHub API](#mise-と-github-api) を参照してリトライする。

### GitHub Codespaces

自動適用される。GitHub の設定で dotfiles リポジトリとして登録するだけでよい。
参考: [Codespaces docs](https://docs.github.com/en/codespaces/setting-your-user-preferences/personalizing-github-codespaces-for-your-account#dotfiles)

**制限事項:**

- 非対話環境で作成されるため `corpUser` / `windowsUser` のプロンプトはスキップされ、空文字になる（`.gitconfig-corp` は適用されない）
- コミット署名（`commit.gpgsign`）は自動で無効化される（1Password SSH エージェントが利用できないため）。Codespaces の [GPG verification](https://docs.github.com/en/codespaces/managing-your-codespaces/managing-gpg-verification-for-github-codespaces) を有効にすると GitHub 管理の鍵で署名できる

任意のリポジトリの Dev Container で dotfiles を適用するケース。VS Code の設定で dotfiles リポジトリを指定すると、コンテナ作成時に `install.sh` が自動実行される。
参考: [Personalizing with dotfile repositories](https://code.visualstudio.com/docs/devcontainers/containers#_personalizing-with-dotfile-repositories)

1. VS Code の Settings → **Dotfiles** で以下を設定:
   - **Repository**: `torumakabe/dotfiles`
   - **Install Command**: `install.sh`（デフォルト、変更不要）
2. Dev Container を作成すると `install.sh` → `chezmoi init --apply` が自動実行される
3. コンテナ起動後にターミナルから手動で実行:
   ```bash
   gh auth login
   GITHUB_TOKEN=$(gh auth token) mise install --yes
   ```

**制限事項:**

- `mise install` はコンテナ作成時にスキップされる（[理由](#mise-と-github-api)）。コンテナ起動後にステップ 3 の手順で手動実行する
- Docker, Go tools, draw.io 等の非 mise 管理ツール（`run_once_after_30-install-tools.sh`）はスキップされる。必要な場合はベースイメージまたは Dev Container Feature で導入する
- 非対話環境で作成されるため `corpUser` / `windowsUser` のプロンプトはスキップされ、空文字になる
- コミット署名（`commit.gpgsign`）は自動で無効化される（1Password SSH エージェントが利用できないため）

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
5. ツールインストール（[詳細](#mise-と-github-api)）:
   ```powershell
   gh auth login
   $env:GITHUB_TOKEN = (gh auth token); mise install; $env:GITHUB_TOKEN = $null
   ```

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
| Linux / WSL | `apt` + `mise` | apt: OS パッケージ + Azure CLI、mise: 開発ツール |
| macOS | `brew` + `mise` | brew: OS パッケージ・GUI アプリ + Azure CLI、mise: 開発ツール |
| Codespaces / Dev Container | ベースイメージ / Feature + `mise` | Feature: Azure CLI 等、mise: 開発ツール |
| Windows | `winget` (DSC) + `mise` | winget: GUI/CLI アプリ + Azure CLI、mise: 開発ツール |
| 全環境共通 | `uv` | Python スクリプト実行（システム Python 不要） |

> **Azure CLI**: mise ではなく各プラットフォームの公式パッケージマネージャーで管理する。Codespaces / Dev Container では devcontainer Feature ([`ghcr.io/devcontainers/features/azure-cli`](https://github.com/devcontainers/features/tree/main/src/azure-cli)) で導入する。

このリポジトリでは、mise の日常的なツール更新を効率化するシェル関数 `mise-upgrade` を `.zshrc` / PowerShell `$PROFILE` に定義している。詳細は [mise 管理ツールの更新](#mise-管理ツールの更新日常操作) を参照。

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

### mise 管理ツールの更新（日常操作）

定期的にツールを最新版にする。シェル関数 `mise-upgrade`（`.zshrc` / `$PROFILE` で定義済み）が以下を一括実行する:

> **初期構築時の注意**: `chezmoi apply` 後は、シェルの設定ファイルがまだ現セッションに読み込まれていない。`mise-upgrade` を使う前にターミナルを再起動するか、手動でリロードすること:
> - bash / zsh: `source ~/.zshrc`
> - PowerShell: `. $PROFILE`

1. `gh auth token` で一時トークンを取得
2. `mise upgrade` で全ツールを最新化
3. `mise lock --platform` で全プラットフォームの lockfile を更新
4. `chezmoi re-add` で lockfile をソースに反映
5. git commit + push

```bash
# bash / zsh / PowerShell 共通
mise-upgrade
```

各ステップでエラーが発生した場合、原因と対処法を表示して即停止する。変更がない場合（全ツール最新）は正常終了する。

他の端末では `chezmoi update` で lockfile が同期され、`mise install` は lockfile の URL から直接ダウンロードする（API 不要、トークン不要）。

<details>
<summary>手動で実行する場合</summary>

`mise lock` は引数なしだと既定の 8 プラットフォーム（musl 含む）を対象にするため、**常に `--platform` を指定する**。

```bash
# bash / zsh
GITHUB_TOKEN=$(gh auth token) mise upgrade
GITHUB_TOKEN=$(gh auth token) mise lock --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
chezmoi re-add ~/.config/mise/mise.lock
cd $(chezmoi source-path)/.. && git add -A && git commit -m "chore: upgrade mise tools" && git push
```

```powershell
# PowerShell
$env:GITHUB_TOKEN = (gh auth token); mise upgrade; mise lock --platform "linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64"; $env:GITHUB_TOKEN = $null
chezmoi re-add ~\.config\mise\mise.lock
cd (Join-Path (chezmoi source-path) ".."); git add -A; git commit -m "chore: upgrade mise tools"; git push
```

</details>

### mise のツール追加・削除（非日常操作）

config.toml にツールを追加または削除するときに行う。

```bash
chezmoi edit ~/.config/mise/config.toml
GITHUB_TOKEN=$(gh auth token) mise install
GITHUB_TOKEN=$(gh auth token) mise lock --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
chezmoi re-add ~/.config/mise/config.toml
chezmoi re-add ~/.config/mise/mise.lock
```

PowerShell の場合は `$env:GITHUB_TOKEN = (gh auth token); <command>; $env:GITHUB_TOKEN = $null` で囲む。`--platform` の値は必ずクォートで囲むこと（例: `--platform "linux-x64,..."`）。PowerShell はカンマを配列演算子として解釈する場合がある。

### mise lockfile の再構築（非日常操作）

以下の状況では lockfile を削除してから `--platform` 付きで再生成する。

- **新しいプラットフォームの端末を使い始める** — lockfile に存在しないプラットフォームを追加する必要がある
- **不要なプラットフォームのエントリを除去したい** — `mise lock` は既存エントリを削除しないため、作り直しが必要
- **lockfile が壊れた** — mise のバグ等で不整合が生じた場合

```bash
rm ~/.config/mise/mise.lock
GITHUB_TOKEN=$(gh auth token) mise lock --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
chezmoi re-add ~/.config/mise/mise.lock
```

### Bootstrap / shell pin の更新

初期セットアップ系スクリプトは、上流の最新版をその場で実行せず、リリース番号・コミット・SHA256 をリポジトリ内に pin している。更新時は **バージョンの更新 → 公式チェックサムの照合 → スクリプト反映** の順で行う。

- `install.sh`
  - `CHEZMOI_VERSION` を更新
  - `https://github.com/twpayne/chezmoi/releases/download/v<version>/chezmoi_<version>_checksums.txt` から利用中プラットフォーム分の SHA256 を更新
- `home/run_once_before_20-install-mise.sh.tmpl`
  - `MISE_VERSION` を更新
  - `https://github.com/jdx/mise/releases/download/<version>/SHASUMS256.txt` から利用中プラットフォーム分の SHA256 を更新
- `home/run_once_after_10-setup-shell.sh.tmpl`
  - `OH_MY_ZSH_COMMIT` は `git ls-remote https://github.com/ohmyzsh/ohmyzsh.git HEAD` などで新しい commit を選んで更新
  - `ZSH_COMPLETIONS_TAG` は GitHub Releases / tags の安定版へ更新

更新後は最低限次を実行して差分を確認する:

```bash
shellcheck install.sh
sed '/^{{/d' home/run_once_before_20-install-mise.sh.tmpl | bash -n
sed '/^{{/d' home/run_once_after_10-setup-shell.sh.tmpl | bash -n
```

### mise と GitHub API

mise はツールのダウンロードに GitHub API を使用する。未認証の場合、レート制限（60 req/hr）に抵触する可能性がある。

**トークンの取得:**

`gh`（GitHub CLI）は mise より先にシステムパッケージ（apt / brew / winget）として導入される。認証後に `gh auth token` で `GITHUB_TOKEN` を取得できる:

```bash
# bash / zsh
gh auth login                         # 初回のみ
GITHUB_TOKEN=$(gh auth token) mise install
```

```powershell
# PowerShell
gh auth login                         # 初回のみ
$env:GITHUB_TOKEN = (gh auth token); mise install; $env:GITHUB_TOKEN = $null
```

`run_once_after_20` は gh が認証済みなら `GITHUB_TOKEN` を自動設定する。初回セットアップで gh が未認証の場合は、セットアップ完了後に上記コマンドでリトライする。

**lockfile による API 呼び出しの削減:**

`mise.lock` は各ツールのダウンロード URL とチェックサムを事前に解決したファイル。config.toml で `lockfile = true` を設定しており、`mise install` / `mise upgrade` ともに lockfile を自動更新する。他端末では `chezmoi update` で lockfile が同期される。lockfile があっても一部の API 呼び出しは発生するため、トークンの設定を推奨する。

| 操作 | GitHub API | トークン |
|------|-----------|---------|
| `mise install`（lockfile あり） | 最小限 | 推奨 |
| `mise upgrade`（ツール更新） | 呼ぶ | 必要 |
| `mise lock`（lockfile 再生成） | 呼ぶ | 必要 |

**注意事項:**

- `GITHUB_TOKEN` を `.zshrc` や `$PROFILE` に常駐させないこと。コマンド単位で一時的に渡す
- ツール追加時は `mise lock --platform` で全プラットフォーム分の lockfile を再生成してからコミットすること

### run_once_ スクリプトの再実行

chezmoi の `run_once_` スクリプトはデフォルトで1回しか実行されない。
再実行が必要な場合:

```bash
# 状態をリセットして再実行
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

### run_once_ スクリプトの実行順と依存関係

このリポジトリでは、`run_once_before_*` → 通常のファイル適用 → `run_once_after_*` の順に処理される。さらに同じフェーズ内ではファイル名の数字順で実行されるため、次の依存関係を前提にしている。

| 順序 | スクリプト | 役割 | 後続が依存している前提 |
|------|-----------|------|------------------------|
| 1 | `run_once_before_10-install-packages.sh` | OS パッケージ (`git`, `zsh` など) を導入 | `git` / `zsh` が後続の shell setup と mise bootstrap までに使える |
| 2 | `run_once_before_20-install-mise.sh` | `mise` 自体を導入 | `run_once_after_20-mise-install.sh` 開始時点で `mise` コマンドが存在する |
| 3 | `run_once_after_10-setup-shell.sh` | Oh My Zsh / plugin / default shell を設定 | `git` / `zsh` は 1 で導入済み。後続スクリプトは新しいログインシェルを前提にしない |
| 4 | `run_once_after_20-mise-install.sh` | `~/.config/mise/config.toml` と `mise.lock` を使ってツール本体を導入 | chezmoi による dotfiles 配置完了後に実行され、`run_once_after_30-install-tools.sh` より先に runtimes / shims を用意する |
| 5 | `run_once_after_30-install-tools.sh` | Docker, Go tools, GUI アプリ等の追加導入 | `mise install` 済みで `go` などのコマンドが PATH に存在する |

変更時は、少なくとも次の前提を確認すること。

- `before_` / `after_` の跨ぎを変えても、`mise` 設定ファイルや lockfile が生成される前に `mise install` しないこと
- `run_once_before_10-install-packages.sh` のパッケージ変更で、後続の `git`, `zsh`, `curl`, package manager 前提を壊していないこと
- `run_once_after_10-setup-shell.sh` は非対話環境でも失敗しないこと。後続スクリプトが「新しい shell を開き直した後」の状態に依存しないこと
- `run_once_after_20-mise-install.sh` の retry / workaround を変える場合、Codespaces とローカル Dev Container の分岐を壊していないこと
- `run_once_after_30-install-tools.sh` の skip 条件を変える場合、Codespaces / Dev Container では引き続きベースイメージや Features 側で補う前提か確認すること

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
├── .chezmoi.toml.tmpl         ← 共通 platform flag・変数定義
├── .chezmoiignore             ← 共通 flag を使ってファイルをスキップ
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
- **コミット署名**: 1Password SSH エージェント経由の SSH 署名をデフォルトで有効化。Dev Container / Codespaces では 1Password エージェントが利用できないため自動で無効化
- **Copilot Guard** フック: bash + PowerShell の二重実装を Python 単一スクリプトに統一
- **uv Enforcer** フック: Copilot エージェントの python/pip 直接実行をブロックし uv 経由を強制
- **SAML SSO ワークアラウンド**: Codespaces の `mise install` で SAML SSO 要求による 403 を回避するため、失敗したツールを認証なしで自動リトライ
- **mise と GitHub API**: lockfile + `gh auth token` によるトークン管理（[詳細](#mise-と-github-api)）
- **Windows**: chezmoi で設定、DSC で GUI アプリ、mise でツール（段階的導入）

## プラットフォーム検出

| 変数名 | 説明 |
|--------|------|
| `.chezmoi.os` | chezmoi 組み込みの OS 値 (`linux`, `darwin`, `windows`) |
| `.isLinux` / `.isMac` / `.isWindows` | `.chezmoi.os` から導出した共通 flag。`.chezmoiignore` と template では基本的にこちらを使う |
| `.isWSL` | Linux 上で `kernel.osrelease` に `microsoft` を含む場合に true |
| `.codespaces` | GitHub Codespaces |
| `.devcontainer` | Dev Container |
| `.windowsUser` | Windows ユーザー名 (Windows 本体または WSL の 1Password パス用) |
| `.corpUser` | 所属企業での Git ユーザー名 |

### Git `includeIf` の設計

`home/dot_gitconfig.tmpl` ではベース設定を `~/.gitconfig` に集約し、`includeIf` でプラットフォーム別の差分だけを読み込む。
これにより、Git 側の判定は「現在のリポジトリのパス接頭辞」に限定し、chezmoi 側の template 分岐を最小限にしている。

- `gitdir:/home/` → Linux / WSL のリポジトリ
- `gitdir:/Users/` → macOS のリポジトリ
- `gitdir/i:C:/`, `gitdir/i:D:/` → Windows のリポジトリ

補足:

- `gitdir` はリポジトリの `.git` ディレクトリのパス接頭辞で判定される
- Windows では drive letter の大文字小文字差を吸収するため `gitdir/i:` を使っている
- この dotfiles は「Windows 上のローカル clone は `C:/` または `D:/` 配下」という前提。別の drive を使う場合は `includeIf "gitdir/i:E:/"` のように追加する
- WSL はパス判定上は Linux (`/home/`) なので `~/.gitconfig-linux` を読み込み、その中で `.isWSL` を使って 1Password 連携パスだけを切り替える
- template の制御構文は `{{- ... -}}` で前後の余分な空行を抑える。`dot_gitconfig-linux.tmpl` の `core.editor` だけは Git に埋め込む引用符を保つため、WSL 側で `\"` を使っている

### コミット署名

1Password の SSH エージェントを使った SSH 署名をデフォルトで有効化している（`commit.gpgsign = true`, `gpg.format = ssh`）。プラットフォーム別の `gpg.ssh.program` は `includeIf` で読み込まれる各 gitconfig で設定される。

| 環境 | `gpg.ssh.program` | ソース |
|------|-------------------|--------|
| macOS | `/Applications/1Password.app/Contents/MacOS/op-ssh-sign` | `dot_gitconfig-mac.tmpl` |
| Linux | `/opt/1Password/op-ssh-sign` | `dot_gitconfig-linux.tmpl` |
| WSL | `/mnt/c/Users/<windowsUser>/.../op-ssh-sign-wsl.exe` | `dot_gitconfig-linux.tmpl` |
| Windows | `C:/Users/<windowsUser>/.../op-ssh-sign.exe` | `dot_gitconfig-windows.tmpl` |

**Dev Container / Codespaces**: 1Password SSH エージェントがコンテナ内に転送されないため、chezmoi テンプレートで `commit.gpgsign = false` に自動切替する（`.codespaces` / `.devcontainer` 変数で判定）。Codespaces では GitHub の [GPG verification](https://docs.github.com/en/codespaces/managing-your-codespaces/managing-gpg-verification-for-github-codespaces) を有効にすることで、GitHub 管理の鍵による署名が可能。

## トラブルシューティング

### `warning: config file template has changed`

`.chezmoi.toml.tmpl` が更新された場合に表示される。設定を再生成する:

```bash
chezmoi init torumakabe
```

> **注意**: リポジトリ名を省略すると、ソースディレクトリが空になり `chezmoi update` が動かなくなる。必ず `torumakabe` を指定すること。

### `mise install` が部分失敗する

GitHub API のレート制限が原因の場合は、[mise と GitHub API](#mise-と-github-api) の手順でトークンを設定してリトライする。

lockfile にないツールがある場合は lockfile を再生成する（手順は「mise lockfile の再構築」を参照）。

```bash
# 未インストールのツールを確認
mise ls --missing

# lockfile を再生成してリトライ（詳細は「mise lockfile の再構築」セクション参照）
rm ~/.config/mise/mise.lock
GITHUB_TOKEN=$(gh auth token) mise lock --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
mise install
```

### `run_once_` スクリプトの warning / error

- **warning として継続**:
  - `run_once_after_10-setup-shell.sh`: デフォルトシェルを zsh に変更できない場合
  - `run_once_after_20-mise-install.sh`: `mise install` 後の一部ツールが未導入のまま残る場合、または状態確認・認証なしリトライの一部が失敗した場合
  - `run_once_after_30-install-tools.sh`: 追加の Go ツール、macOS の cask、Linux の draw.io など任意ツールの導入に失敗した場合
- **error として停止**:
  - Oh My Zsh の clone、Docker 本体の導入など、セットアップ継続に必要な主要処理（`mise install` 自体の失敗は上記のとおり warning で継続）

warning は標準エラーに明示表示される。表示されたコマンドを手動で再実行して復旧できる。

### `run_once_` スクリプトが sudo を要求して停止する

Codespaces 以外の環境では、パッケージインストールに sudo が必要。
パスワードを入力するか、sudoers を設定する。

### Dev Container で mise ツールが入っていない

コンテナ作成時に `mise install` は自動スキップされる（[理由](#mise-と-github-api)）。
[Dev Container のクイックスタート](#dev-container-ローカル) のステップ 3 を実行する。
