# Architecture Guide

README から分離した、構成と設計判断の詳細である。運用手順は [`docs/operations.md`](operations.md) を参照。

## ディレクトリ構造

```text
home/                           ← chezmoi source (.chezmoiroot で指定)
├── .chezmoi.toml.tmpl          ← 共通 flag・変数定義
├── .chezmoiignore              ← 条件付き除外
├── .chezmoiremove              ← 不要ファイルの削除
├── dot_gitconfig*.tmpl         ← Git 設定
├── dot_zshrc.tmpl              ← zsh 設定（対話シェル）
├── dot_zprofile.tmpl           ← zsh login 時に ~/.profile を source
├── dot_bash_profile.tmpl       ← bash login 時に ~/.profile を source
├── dot_profile.tmpl            ← POSIX 互換の共通 env（PATH, brew shellenv, mise shims）
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

## PATH 管理（非対話シェル対応）

非対話シェル（Copilot CLI エージェント、IDE、スクリプト）では `.zshrc` / `$PROFILE` が読まれず、mise 管理ツールや brew 管理ツールが PATH から欠落する。これを解消するため、**POSIX 互換の `~/.profile` に共通 env を集約**し、各シェルから読み込む。

| OS | 仕込み先 | 仕込み内容 |
|----|----------|-----------|
| macOS / Linux / WSL | `~/.profile` | brew shellenv（macOS）、`GOPATH`、`~/.local/bin` / `~/go/bin` / `~/.cargo/bin`、mise shims |
| macOS / Linux / WSL | `~/.zprofile` | `~/.profile` を source するだけ（zsh は `.profile` を直接読まないため） |
| macOS / Linux / WSL | `~/.bash_profile` | `~/.profile` を source するだけ（`.bash_profile` が存在すると bash は `.profile` を読まないため） |
| Windows | ユーザー環境変数 `Path` | `%LOCALAPPDATA%\mise\shims` を先頭追記（`run_once_after_05` が実施） |

### なぜ `~/.profile` か

- **sh / dash / bash(login)** は `~/.profile` を直接読む
- **zsh(login)** は `.profile` を読まないため `~/.zprofile` から source する
- **非対話 shell（`bash -c`, IDE agent の直接 exec）** は親プロセスから env 継承する。親が login shell 経由で起動される限り PATH は伝播する
- **macOS GUI アプリ**（Dock / Finder / Spotlight から起動、launchd 直下）は shell を介さないため `~/.profile` が実行されない。プロセスは launchd の既定 PATH（`/etc/paths` + `/etc/paths.d/*`）だけを継承する。Ghostty など shell を spawn する GUI ターミナルは login shell を起動するので今回の修正で解決するが、Copilot Desktop のように shell を介さず子プロセスに外部ツールを exec するアプリは影響を受ける可能性がある。その場合のワークアラウンド:
  - 当該アプリから呼ぶコマンドを絶対パスで指定する
  - `~/Library/LaunchAgents/*.plist` に `launchctl setenv PATH` 相当を仕込む（環境全体に影響するため慎重に）
  - 参考: [`launchd.plist(5)`](https://ss64.com/mac/launchd.plist.html) の `EnvironmentVariables` キー、[Apple Developer: Daemons and Services Programming Guide](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)

  現状このリポジトリでは対応していない（Copilot Desktop は `dot_zshrc.tmpl` の `launchctl setenv COPILOT_CLI_PATH` で個別対応済みのため）。

### brew shellenv を入れる理由

Apple Silicon の Homebrew は `/opt/homebrew/bin` にあるが、launchd 既定 PATH や `/etc/paths` には含まれない。`brew shellenv` を `~/.profile` で実行することで、非対話シェルや GUI 起動子プロセスからも `copilot`・`azd`・`gh` 等の brew 管理ツールが解決できる。

### mise shims と `mise activate` の共存

`mise activate` と shims は共存可能。対話 zsh では `.zshrc` の `mise activate zsh`（フル版）が shims を PATH から除去して自前挿入するため、hooks や `[env]` による環境変数注入が有効。非対話シェルでは shims のみ PATH に乗り、バイナリ解決だけ成立する。

### shims 方式の制限

`mise activate` のみで有効で shims では動かない機能:

1. `mise.toml` の `[env]` セクションによる環境変数自動注入
2. `hooks`（ディレクトリ移動時フック）
3. `_.file` / `_.source`（env ファイル読込）

このリポジトリの `~/.config/mise/config.toml` は `[tools]` と `[settings]` のみ使用しており、上記機能は未使用のため実害なし。非対話シェルで環境変数が必要な場合は `mise exec -- <cmd>` を使う。

参考: <https://mise.jdx.dev/dev-tools/shims.html>

## `run_once_*` スクリプトの実行順と依存関係

chezmoi は `run_once_before_*` → 通常ファイル適用 → `run_once_after_*` の順に処理し、同じフェーズ内では数字順で実行する。

| 順序 | スクリプト | 役割 | 依存前提 |
|------|-----------|------|----------|
| 1 | `run_once_before_10-install-packages.sh` | OS パッケージ導入 | 後続で `git` / `zsh` を使える |
| 2 | `run_once_before_20-install-mise.sh` | `mise` 自体を導入 | 後続で `mise` が存在する |
| 3 | `run_once_after_05-setup-mise-shims-path.ps1` | Windows: mise shims をユーザー PATH に追加 | `mise` 導入済み（Windows は DSC 経由） |
| 4 | `run_once_after_10-setup-shell.sh` | shell 設定 | `git` / `zsh` は導入済み |
| 5 | `run_once_after_20-mise-install.sh` | `config.toml` / `mise.lock` を使ってツール導入 | dotfiles 配置後に動く |
| 6 | `run_once_after_30-install-tools.sh` | 追加ツール導入 | `mise install` 済み |

変更時は、`mise` 設定が配置される前に `mise install` しないことと、Codespaces / Dev Container の分岐を壊さないことを優先して確認する。
