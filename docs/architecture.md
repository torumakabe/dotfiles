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
├── dot_zshenv.tmpl             ← 非login zsh (VS Code 統合ターミナル等) から ~/.profile を source
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
| macOS / Linux / WSL | `~/.profile` | brew shellenv（macOS）、`GOPATH`、`~/.local/bin` / `~/go/bin` / `~/.cargo/bin`、mise shims。`__DOTFILES_PROFILE_LOADED` ガードで再実行を抑止 |
| macOS / Linux / WSL | `~/.zprofile` | `~/.profile` を source（login zsh は `.profile` を直接読まないため） |
| macOS / Linux / WSL | `~/.zshenv` | `~/.profile` を source（VS Code 統合ターミナル等の非login zsh 対策。ガードで login シェルでの二重実行を抑止） |
| macOS / Linux / WSL | `~/.bash_profile` | `~/.profile` を source（`.bash_profile` が存在すると bash は `.profile` を読まないため） |
| macOS / Linux / WSL | `~/.bashrc` | interactive non-login bash（GUI アプリが spawn する bash 等）向けに `~/.profile` を source する。非対話は早期 return。末尾で `~/.bashrc.local` を読み distro default の alias/PS1 を退避可能 |
| macOS (Copilot CLI SDK 対策) | `~/.local/bin/<tool>` へ mise shim を symlink | GitHub Desktop の Copilot SDK が独自に組み立てる PATH には `~/.local/bin` が含まれるため、必要な mise 管理ツールだけ symlink して解決可能にする（`run_onchange_after_21-link-mise-shims.sh` が実施） |
| Windows | ユーザー環境変数 `Path` | `%LOCALAPPDATA%\mise\shims` を先頭追記（`run_once_after_05` が実施） |

### なぜ `~/.profile` か

- **sh / dash / bash(login)** は `~/.profile` を直接読む
- **zsh(login)** は `.profile` を読まないため `~/.zprofile` から source する
- **zsh(非login)** は `~/.zshenv` しか読まない。VS Code 統合ターミナルで `args: []` を指定した場合など、brew 管理ツール (`copilot`, `gh` の一部, completion 等) が PATH から欠落し `.zshrc` 内の `brew --prefix` 参照が壊れるため、`~/.zshenv` から `~/.profile` を source する
- **bash(interactive non-login)** は `~/.bashrc` のみ読む。nested bash（zsh → bash、tmux pane）や ssh login 後の対話 bash で PATH を揃える
- **非対話 shell（`bash -c`, IDE agent の直接 exec）** は親プロセスから env 継承する。親が login shell 経由で起動される限り PATH は伝播する
- **macOS GUI アプリ**（Dock / Finder / Spotlight から起動、launchd 直下）は shell を介さないため `~/.profile` が実行されない。プロセスは launchd の既定 PATH（`/etc/paths` + `/etc/paths.d/*`）だけを継承する。特に **GitHub Desktop の Copilot SDK は `bash --norc --noprofile` で bash を spawn する**うえ、親プロセス (`copilot --server`) が独自に hardcoded PATH を組み立てるため、`.bashrc` / `.bash_profile` / `.profile` / `BASH_ENV` / `launchctl setenv PATH` いずれの経路でも PATH を注入できない。
  - Copilot CLI の PATH には **`~/.local/bin` だけは確実に含まれる**ため、`run_onchange_after_21-link-mise-shims.sh` が `~/.local/share/mise/shims/<tool>` を `~/.local/bin/<tool>` へ symlink して解決可能にしている。symlink 先は shim なので mise のバージョン切替にも追従する。
  - 対象ツールはスクリプトが **mise shims を自動走査** して決定する。言語ランタイム本体 (`node`/`npm`/`npx`/`corepack`, `dotnet`/`dnx`, `cargo`/`rustc`/`rustup`/`rustfmt`/`rustdoc`/`clippy-driver`/`rls`) とランタイム付随物 (`cargo-*`, `rust-*`) および shim ではない補助ファイル (`*.bat`, `*.ps1`, `*.sh`, `*.zst`, `*.txt`, `*-darwin-*`) は除外。除外方針を変えたい場合はスクリプト内の `EXCLUDE_EXACT` / `EXCLUDE_PATTERN` を編集する。
  - 本スクリプトが作成したリンクは `${XDG_STATE_HOME:-~/.local/state}/chezmoi-dotfiles/mise-shim-links` に記録される。**掃除対象は state file に記録された過去の管理対象のみ** — ユーザーが手動で作った symlink や非 symlink は一切触れない。
  - 本スクリプトは `run_onchange_` プレフィックスと `~/.config/mise/config.toml` のハッシュ埋め込みにより、mise ツール一覧が変わったときに再実行される。`run_onchange_after_21-` と命名し、`run_once_after_20-mise-install` の後に実行される順序を保証している (fresh bootstrap で mise install 前に no-op 終了しないように)。
  - 本スクリプトは darwin 限定 (`{{ if eq .chezmoi.os "darwin" }}` ガード)。Linux では mise shims が `~/.profile` 経由で PATH に含まれるため symlink 不要、Windows は `run_once_after_05` がレジストリに PATH 追加済のため不要。

### `~/.profile` 再実行の抑止とコスト

`~/.profile` は `__DOTFILES_PROFILE_LOADED` を export することで、**同一プロセスツリー内の nested shell** (login zsh inside login bash, `zsh -c` from a sourced shell, etc.) で二重実行を防ぐ。

| ケース | コスト実測 (macOS, `zsh -c true`) |
|--------|----------------------------------|
| Cold (ガード未継承, 例: launchd 直下から fresh zsh) | ~37ms (うち `brew shellenv` の Ruby 起動が ~30ms) |
| Warm (ガード継承済み) | ~7ms |

ターミナル起動時に 1 回支払われる 37ms は体感できないため、`~/.zshenv` からの source を許容する設計とした。スクリプトで大量に `zsh -c` を spawn するケースでは、親プロセスで `__DOTFILES_PROFILE_LOADED=1` を export しておけば全子プロセスでスキップされる。

#### mise shim symlink の運用ガイドライン

**動作原理**: `run_onchange_after_21-link-mise-shims.sh` は `~/.local/share/mise/shims/` を走査し、除外リストに該当しない全ての実行可能な regular file を `~/.local/bin/` へ symlink する。`chezmoi apply` 時、mise のツール追加・削除に自動追従する。

**除外設計の根拠**:

- **言語ランタイム本体** (`node`, `cargo`, `dotnet` 等): VS Code や他の IDE が `~/.local/bin` を優先して拾うと、mise の想定外バージョンで起動し `mise.toml` の `[env]` 等が効かない副作用が起きるため除外
- **ランタイム付随サブコマンド** (`cargo-*`, `rust-*`): 親コマンド (`cargo`, `rustc`) が除外されると無意味、かつ単独呼び出しは稀なため除外
- **補助ファイル** (`*.bat`, `*.ps1`, `*.sh`, `*.zst`, `*.txt`, `*-darwin-*`): shim ではない付属ファイル (azd の platform variant 等)

**除外を変更するタイミング**:

- 除外中のツールを Copilot CLI から直接使いたくなった → `EXCLUDE_EXACT` から該当エントリを削除
- 特定 shim が副作用を起こす → `EXCLUDE_EXACT` または `EXCLUDE_PATTERN` に追加

**運用フロー**:

1. 除外リストを変更したい場合は `home/run_onchange_after_21-link-mise-shims.sh.tmpl` を編集
2. `chezmoi apply` (スクリプトの sha が変わるため自動で再実行される)
3. `ls -la ~/.local/bin/` で差分を確認。除外に追加したものは state file 経由で自動削除される

**自動掃除の安全性**:

- 本スクリプトが作った symlink のみが state file に記録される
- 除外リスト追加 or mise 側でツール削除 → 次回 `chezmoi apply` 時に state file と突き合わせて自動 unlink
- ユーザーが手動で `~/.local/bin` に置いた symlink / 実バイナリは state file に無いため絶対に触れない (例: `uv` が独立インストール済の場合、そのまま保護される)

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
