# Architecture Guide

README から分離した、構成と設計判断の詳細である。運用手順は [`docs/operations.md`](operations.md) を参照。

## ディレクトリ構造

```text
home/                           ← chezmoi source
├── .chezmoi.toml.tmpl          ← 共通 flag・変数定義
├── .chezmoiignore              ← 条件付き除外
├── .chezmoiremove              ← 不要ファイルの削除（現在は ~/.mise.toml）
├── dot_gitconfig*.tmpl         ← Git 設定
├── dot_zshrc.tmpl              ← 対話 zsh
├── dot_profile.tmpl            ← POSIX 互換の共通 env（PATH, brew shellenv, mise shims）
├── dot_{zprofile,zshenv,bash_profile,bashrc}.tmpl ← 全て ~/.profile を source
├── dot_config/git/hooks/pre-commit  ← gitleaks + ローカルフック委譲
├── dot_config/mise/{config.toml.tmpl,mise.lock}
├── PowerShell_profile.ps1.tmpl
├── private_dot_copilot/        ← ~/.copilot/ 配下（instructions, hooks, mcp, skills）
└── run_once_{before,after}_*   ← bootstrap スクリプト
reference/windows/configuration.dsc.yaml  ← WinGet DSC（参照専用）
```

## 主要な決定事項

- 設定配布 `chezmoi` / ツール版管理 `mise` / Python 実行 `uv`
- Git の環境差分は `includeIf`、コミット署名は 1Password SSH エージェント（コンテナ系は自動無効化）
- `copilot-guard.py` / `uv-enforcer.py` / `node-global-enforcer.py` でネットワーク以外の危険操作を抑止、`postToolUse` で監査ログ
- Copilot CLI local sandbox を有効化
- `copilot-guardrails` で利便性と秘匿環境変数の扱いを固定
- `gitleaks` 付き pre-commit を配布

## Copilot Guard の設計

`copilot-guard.py` は `preToolUse` フックで以下を検査する。優先度は **deny > ask > allow**。

1. 秘匿ファイル拒否 (`blocked-files.txt`)
2. 確認付きアクセス (`ask-files.txt`)
3. 機微な環境変数の読み取り拒否 (`printenv`, `$TOKEN`, `os.environ` 等)。通常使う変数は許可リストで除外
4. `git commit` の明示承認

パス比較前に `\` を `/` へ正規化する。パターンファイルは `/` 前提で書く。

shell command の外部ネットワーク通信は、`~/.copilot/settings.json` の `sandbox.userPolicy.network` で設定する。初期状態では sandbox を有効化するだけにとどめ、外向き通信の遮断や host rule は設定しない。

## git pre-commit フック

グローバル `pre-commit` を `~/.config/git/hooks/pre-commit` に配置し `core.hooksPath` で有効化。`gitleaks git --pre-commit --staged --redact` の後、リポジトリローカルの `.git/hooks/pre-commit` があれば追加実行する。

## プラットフォーム検出

| 変数 | 説明 |
|------|------|
| `.chezmoi.os` | `linux`, `darwin`, `windows` |
| `.isLinux` / `.isMac` / `.isWindows` | 上から導出 |
| `.isWSL` | Linux かつ `kernel.osrelease` に `microsoft` を含む |
| `.codespaces` / `.devcontainer` | 各環境判定 |
| `.windowsUser` / `.corpUser` | 初回セットアップで入力 |

## Git `includeIf`

`home/dot_gitconfig.tmpl` はベース設定のみを置き、`includeIf` でプラットフォーム差分を切り替える: `gitdir:/home/` → Linux/WSL、`gitdir:/Users/` → macOS、`gitdir/i:C:/` 等 → Windows。WSL は Linux 側を読みつつ `.isWSL` で 1Password 連携パスを切り替える。

## コミット署名

1Password SSH エージェントで SSH 署名する。`gpg.ssh.program` は環境別: macOS `/Applications/1Password.app/.../op-ssh-sign`、Linux `/opt/1Password/op-ssh-sign`、WSL `~/.local/bin/op-ssh-sign-wrapper.sh`（ADR-012: `op-ssh-sign-wsl.exe` の CRLF 出力を補正）、Windows `C:/Users/<windowsUser>/.../op-ssh-sign.exe`。Dev Container / Codespaces では `commit.gpgsign = false`。

## PATH 管理（非対話シェル対応）

非対話シェル（Copilot CLI エージェント、IDE、スクリプト）では `.zshrc` / `$PROFILE` が読まれず、mise / brew 管理ツールが PATH から欠落する。対策として **POSIX 互換の `~/.profile` に共通 env を集約**し、各シェル起動ファイルから source する。

| OS | 仕込み先 | 内容 |
|----|---------|------|
| Unix 共通 | `~/.profile` | brew shellenv、`GOPATH`、`~/.local/bin` / `~/go/bin` / `~/.cargo/bin`、mise shims。`__DOTFILES_PROFILE_LOADED` で再実行抑止 |
| Unix 共通 | `~/.zprofile` / `~/.zshenv` / `~/.bash_profile` / `~/.bashrc` | いずれも `~/.profile` を source（login / 非login / 対話 bash を網羅） |
| macOS のみ | `~/.local/bin/<tool>` への mise shim symlink | `run_onchange_after_21-link-mise-shims.sh` が自動生成 |
| Windows | ユーザー環境変数 `Path` | `run_once_after_05` が `%LOCALAPPDATA%\mise\shims` を先頭追記 |

### 各シェルの読み込み経路

`sh` / `bash(login)` は `.profile` を直接、`zsh(login)` は `.zprofile`、`zsh(非login)` は `.zshenv`、`bash(interactive non-login)` は `.bashrc` のみ読む。いずれからも `~/.profile` に誘導することで PATH が揃う。`bash -c` 等の非対話は親から env 継承する。

### macOS GUI アプリ経由の PATH 注入

Dock / Spotlight / GitHub Desktop から起動された子プロセスは launchd 既定 PATH しか継承しない。特に **GitHub Desktop の Copilot SDK は `bash --norc --noprofile` で bash を spawn し、親が独自の hardcoded PATH を組む**ため、`.bashrc` / `BASH_ENV` / `launchctl setenv` では PATH 注入不可。唯一 **`~/.local/bin` だけは確実に含まれる**ため、`run_onchange_after_21-link-mise-shims.sh` が mise shims をそこへ symlink する。

- 言語ランタイム本体（`node`, `cargo`, `dotnet` 等）とサブコマンド・補助ファイルは除外。リストはスクリプト内の `EXCLUDE_EXACT` / `EXCLUDE_PATTERN` を編集
- 作成 symlink は state file (`${XDG_STATE_HOME}/chezmoi-dotfiles/mise-shim-links`) に記録され、管理対象だった symlink のみ自動掃除。手動で作ったものには触れない
- darwin 限定。Linux は `~/.profile` 経由、Windows は `run_once_after_05` で解決済み

### mise shims の制約

mise は shims と `mise activate` を併用する。対話 zsh では `mise activate zsh` が shims を除去して自前挿入し、`[env]` / hooks が効く。非対話シェルでは shims のみで解決する。shims では `[env]` / `hooks` / `_.file` が動かないが、本 repo の `config.toml` は `[tools]` / `[settings]` のみ使用するため影響なし（必要時は `mise exec -- <cmd>`）。詳細: <https://mise.jdx.dev/dev-tools/shims.html>

## MSVC リンカー解決 (Windows)

Windows で cargo が `windows-msvc` ターゲットをビルドするには MSVC の `link.exe` が必要（[ADR-017](adr/017-msvc-linker-env-var-override-windows.md)）。winget で導入する Coreutils for Windows の `link.exe`（ハードリンク作成コマンド）と名前が衝突し、Machine PATH 側が優先されるため PATH の並び替えでは解決できない。

- `reference/windows/configuration.dsc.yaml` で Visual Studio 2022 Build Tools + C++ ワークロード (`Microsoft.VisualStudio.Workload.VCTools`) を導入
- `run_onchange_after_20-resolve-msvc-linker.ps1` が `vswhere.exe` で現在の `link.exe` を解決し、ユーザー環境変数 `CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER` に設定する。PATH に依存しないため $PROFILE を読まないシェル（Copilot CLI 等）でも有効
- `{{ now }}` を script hash に埋め込み `chezmoi apply` の度に再評価するため、VS Build Tools の更新でツールセットのバージョンフォルダが変わっても追従する

## `run_once_*` スクリプトの実行順

chezmoi は `run_once_before_*` → 通常ファイル適用 → `run_once_after_*` の順に処理し、同フェーズ内は数字順で実行する。

| # | スクリプト | 役割 |
|---|-----------|------|
| 1 | `before_10-install-packages.sh` | OS パッケージ導入 |
| 2 | `before_20-install-mise.sh` | `mise` 本体導入 |
| 3 | `after_05-setup-mise-shims-path.ps1` | Windows: mise shims を PATH 追加 |
| 4 | `after_10-setup-shell.sh` | shell 設定 |
| 5 | `after_20-mise-install.sh` | `config.toml` に従ってツール導入 |
| 6 | `after_30-install-tools.sh` | 追加ツール導入 |

変更時は、mise 設定配置前に `mise install` しないこと、Codespaces / Dev Container の分岐を壊さないことを確認する。
