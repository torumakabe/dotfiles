# Architecture Guide

README から分離した、構成と設計判断の詳細である。

## ディレクトリ構造

```text
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
│   ├── git/
│   │   └── hooks/
│   │       └── pre-commit     ← gitleaks + ローカルフック委譲のグローバル pre-commit
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
│   │       ├── copilot-guard.py
│   │       └── uv-enforcer.py
│   └── skills/
├── run_once_before_*          ← パッケージ・mise インストール
└── run_once_after_*           ← シェル・ツールセットアップ
reference/windows/             ← デプロイしない参照ファイル
├── configuration.dsc.yaml     ← WinGet DSC (手動実行)
└── winterm-settings.json      ← Windows Terminal テーマ
.github/
└── copilot-instructions.md    ← リポジトリレベル Copilot 指示
```

`.chezmoiremove` は `chezmoi apply` 時にホームディレクトリから不要になったファイルを自動削除する。現在は `~/.mise.toml` を対象としている。

## 主要な決定事項

- **chezmoi** が設定ファイルの配置・テンプレート化・プラットフォーム分岐を担当
- **mise** が全プラットフォームでツールバージョンを管理
- **uv** が Python 実行を管理し、システム Python 依存を減らす
- **Git includeIf** を使って、プラットフォーム別 gitconfig の差分だけを自動読込する
- **コミット署名** は 1Password SSH エージェント経由を基本とし、コンテナ系環境では自動無効化する
- **Copilot Guard / uv Enforcer** により、危険なファイルアクセスや Python / pip の直接実行を抑止する
- **gitleaks + git pre-commit** により、コミット前に secret scan を走らせつつ、各リポジトリ固有のフックも併用できる
- **Codespaces / Dev Container** では、非対話での作成や認証制約に合わせたワークアラウンドとフォールバックを持つ

## Copilot Guard の設計

`copilot-guard.py` は `preToolUse` フックとして、エージェントのツール呼び出しを**実行前にテキスト検査**し、秘匿情報の漏洩リスクがある操作を拒否する。

### 設計上の位置づけ

このフックは**エージェント向けのガードレール**である。LLM エージェントは通常、最も自然なコード（`printenv`、`echo $SECRET`、`os.environ` 等）を生成するため、そのパターンをブロックするだけで大部分のリスクをカバーできる。Base64 エンコードや変数間接参照などの難読化には対応しないが、プロンプトインジェクション等の悪意ある介入がない限り、エージェントがそのようなコードを生成する可能性は低い。`blocked-files.txt` によるファイルブロックも同様に、テキストベースの検査で実用上十分なカバー範囲を得る設計である。

### 3 つのチェック層

```text
preToolUse 入力 (JSON)
  │
  ├─ 1. ファイルアクセスチェック ← blocked-files.txt
  │     対象: 全ツールの path/file/uri/glob/command 引数
  │
  ├─ 2. 環境変数アクセスチェック ← コード内定義
  │     対象: bash/powershell の command 引数のみ
  │     - 列挙コマンド (printenv, env, declare -p, ...)
  │     - 秘匿変数展開 ($SECRET, $TOKEN, ...)
  │     - ランタイム全体ダンプ (os.environ, process.env, ...)
  │     ※ 汎用変数 ($PATH, $HOME, ...) は許可リストで除外
  │
  └─ 3. URL 許可リストチェック ← allowed-urls.txt
        対象: command 内の URL、web_fetch の url 引数
```

### 環境変数の許可リスト設計

環境変数チェックでは `$VAR` / `${VAR}` 展開を検査するが、全変数をブロックするとエージェントの通常作業が阻害される。そこで以下のルールで判定する:

1. 変数名が許可リスト（`PATH`、`HOME`、`SHELL`、`SSH_AUTH_SOCK` 等 50 以上）に含まれれば**常に許可**
2. 変数名に秘匿フラグメント（`secret`、`token`、`key`、`password`、`credential`、`auth` 等）が含まれれば**ブロック**
3. 上記のいずれにも該当しない変数は**許可**（未知の変数はブロックしない）

この設計は「偽陽性（正当な操作のブロック）を最小化し、明らかに危険なパターンだけを止める」方針に基づく。

## git pre-commit フック

グローバル `pre-commit` フックは `home/dot_config/git/hooks/executable_pre-commit` から `~/.config/git/hooks/pre-commit` に配置され、`~/.gitconfig` の `core.hooksPath` で有効化される構成である。

このフックは次の 2 段構えで動作する。

1. `gitleaks git --pre-commit --staged --redact --verbose --no-banner` で staged 変更を検査する
2. 各リポジトリに `.git/hooks/pre-commit` が存在すれば、それを追加で呼び出す

これにより、dotfiles 側で共通の secret scan を強制しつつ、各リポジトリ固有のフック実装も失わない構成になっている。

## プラットフォーム検出

| 変数名 | 説明 |
|--------|------|
| `.chezmoi.os` | chezmoi 組み込みの OS 値 (`linux`, `darwin`, `windows`) |
| `.isLinux` / `.isMac` / `.isWindows` | `.chezmoi.os` から導出した共通 flag |
| `.isWSL` | Linux 上で `kernel.osrelease` に `microsoft` を含む場合に true |
| `.codespaces` | GitHub Codespaces |
| `.devcontainer` | Dev Container |
| `.windowsUser` | Windows ユーザー名 |
| `.corpUser` | 所属企業での Git ユーザー名 |

## Git `includeIf` の設計

`home/dot_gitconfig.tmpl` ではベース設定を `~/.gitconfig` に集約し、`includeIf` でプラットフォーム別の差分だけを読み込む。

- `gitdir:/home/` → Linux / WSL のリポジトリ
- `gitdir:/Users/` → macOS のリポジトリ
- `gitdir/i:C:/`, `gitdir/i:D:/` → Windows のリポジトリ

補足:

- `gitdir` はリポジトリの `.git` ディレクトリのパス接頭辞で判定される
- Windows では drive letter の大文字小文字差を吸収するため `gitdir/i:` を使う
- WSL はパス判定上は Linux (`/home/`) なので `~/.gitconfig-linux` を読み込み、その中で `.isWSL` を使って 1Password 連携パスだけを切り替える
- template の制御構文は `{{- ... -}}` で前後の余分な空行を抑える

## コミット署名

1Password の SSH エージェントを使った SSH 署名をデフォルトで有効化している（`commit.gpgsign = true`, `gpg.format = ssh`）。`gpg.ssh.program` はプラットフォームごとに切り替える。

| 環境 | `gpg.ssh.program` | ソース |
|------|-------------------|--------|
| macOS | `/Applications/1Password.app/Contents/MacOS/op-ssh-sign` | `dot_gitconfig-mac.tmpl` |
| Linux | `/opt/1Password/op-ssh-sign` | `dot_gitconfig-linux.tmpl` |
| WSL | `/mnt/c/Users/<windowsUser>/.../op-ssh-sign-wsl.exe` | `dot_gitconfig-linux.tmpl` |
| Windows | `C:/Users/<windowsUser>/.../op-ssh-sign.exe` | `dot_gitconfig-windows.tmpl` |

Dev Container / Codespaces では 1Password SSH エージェントがコンテナ内に転送されないため、chezmoi テンプレートで `commit.gpgsign = false` に自動切替する。Codespaces では GitHub の [GPG verification](https://docs.github.com/en/codespaces/managing-your-codespaces/managing-gpg-verification-for-github-codespaces) を有効にすることで、GitHub 管理の鍵による署名が可能である。

## `run_once_` スクリプトの実行順と依存関係

chezmoi は `run_once_before_*` → 通常のファイル適用 → `run_once_after_*` の順に処理する。さらに同じフェーズ内ではファイル名の数字順で実行される。

| 順序 | スクリプト | 役割 | 後続が依存している前提 |
|------|-----------|------|------------------------|
| 1 | `run_once_before_10-install-packages.sh` | OS パッケージを導入 | `git` / `zsh` が後続の shell setup と mise bootstrap までに使える |
| 2 | `run_once_before_20-install-mise.sh` | `mise` 自体を導入 | `run_once_after_20-mise-install.sh` 開始時点で `mise` コマンドが存在する |
| 3 | `run_once_after_10-setup-shell.sh` | Oh My Zsh / plugin / default shell を設定 | `git` / `zsh` は 1 で導入済み |
| 4 | `run_once_after_20-mise-install.sh` | `~/.config/mise/config.toml` と `mise.lock` を使ってツール本体を導入 | chezmoi による dotfiles 配置完了後に実行される |
| 5 | `run_once_after_30-install-tools.sh` | Docker, Go tools, GUI アプリなどの追加導入 | `mise install` 済みで `go` などのコマンドが PATH に存在する |

### 変更時の確認事項

- `before_` / `after_` の跨ぎを変えても、`mise` 設定ファイルや lockfile が生成される前に `mise install` しないこと
- `run_once_before_10-install-packages.sh` のパッケージ変更で、後続の前提を壊していないこと
- `run_once_after_10-setup-shell.sh` は非対話実行でも失敗しないこと
- `run_once_after_20-mise-install.sh` の retry / workaround を変える場合、Codespaces とローカル Dev Container の分岐を壊していないこと
- `run_once_after_30-install-tools.sh` の skip 条件を変える場合、Codespaces / Dev Container では引き続きベースイメージや Features 側で補う前提か確認すること
