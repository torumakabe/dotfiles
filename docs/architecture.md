# Architecture Guide

README から分離した、構成と設計判断の詳細である。運用手順は [`docs/operations.md`](operations.md) を参照。

## ディレクトリ構造

```text
home/                           ← chezmoi source
├── .chezmoi.toml.tmpl          ← 共通 flag・変数定義
├── .chezmoiignore              ← 条件付き除外
├── .chezmoiremove              ← 不要ファイルの削除
├── .chezmoidata.toml            ← 望ましい版・最小版・公式 asset の宣言
├── dot_gitconfig*.tmpl         ← Git 設定
├── dot_zshrc.tmpl              ← 対話 zsh
├── dot_profile.tmpl            ← POSIX 互換の共通 env（PATH, brew shellenv, mise shims）
├── dot_{zprofile,zshenv,bash_profile,bashrc}.tmpl ← 全て ~/.profile を source
├── dot_config/git/templates/hooks/executable_pre-commit  ← gitleaks (init.templateDir 経由)
├── dot_local/bin/executable_gitleaks-pre-commit          ← gitleaks (設定ベースフック経由)
├── dot_config/mise/{config.toml.tmpl,private_mise.lock}
├── PowerShell_profile.ps1.tmpl
├── private_dot_copilot/        ← ~/.copilot/ 配下（instructions, hooks, mcp, skills）
└── run_once_{before,after}_*   ← bootstrap スクリプト
.devcontainer/devcontainer.json  ← このリポジトリを開発する Dev Container の構成
reference/windows/configuration.dsc.yaml  ← WinGet DSC（参照専用）
```

## 主要な決定事項

- 設定配布 `chezmoi` / 汎用ツール版管理 `mise` / Python 実行 `uv`
- GitHub CLI・jq・uv は mise の管理外で、ツールごとの公式導入経路を使う（[ADR-028](adr/028-remove-mise-use-official-per-tool-install-paths.md)）
- Git の環境差分は `includeIf`、コミット署名は 1Password SSH エージェント（コンテナ系は自動無効化）
- `copilot-guard.py` / `uv-enforcer.py` / `node-global-enforcer.py` でネットワーク以外の危険操作を抑止、`postToolUse` で監査ログ
- Copilot CLI local sandbox は環境別の初期値を user-level settings へ設定し、OS 別 backend で shell と filesystem policy を適用
- `copilot-guardrails` で利便性と秘匿環境変数の扱いを固定
- `gitleaks` 付き pre-commit を `init.templateDir`（ADR-018）と設定ベースフック（ADR-020）の 2 レイヤで配布

## Copilot Guard の設計

`copilot-guard.py` は `preToolUse` フックで以下を検査する。優先度は **deny > ask > no opinion（空出力）**（[ADR-006](adr/006-pretooluse-hook-no-allow.md)）。

1. ファイル操作と読み取り専用検索のプロジェクト配下パス例外 (`allowed-files.txt`)
2. 秘匿ファイル拒否 (`blocked-files.txt`)
3. 確認付きアクセス (`ask-files.txt`)
4. 機微な環境変数の読み取り拒否 (`printenv`, `$TOKEN`, `os.environ` 等)。通常使う変数は許可リストで除外
5. `git commit` の明示承認

パス比較前に `\` を `/` へ正規化する。`allowed-files.txt` は、ワイルドカードのない単一のプロジェクト相対パスを `/` 前提で書く。ファイルツールが絶対パスを渡した場合は、現在のプロジェクトルート配下にあるパスだけを相対パスへ変換して例外と照合する。読み取り専用の `rg` と `glob` にも例外を適用するが、検索フィルターはワイルドカードのない許可パスに限定し、明示された検索ルートがすべてプロジェクト内にあることを確認する。シンボリックリンク、ジャンクション、file URI、`..` を含むパス、シェルコマンドには例外を適用しない。`apply_patch` は freeform 引数から `Add File`、`Update File`、`Delete File`、`Move to` の対象パスを抽出し、同じパス判定へ渡す。
各 command hook は `~/.local/bin/uv` 経由の `uv run` で起動する。`uv` は mise の管理外にあり、shim もバージョン解決も挟まないため、他ツールの missing 状態はフックの終了状態へ影響しない。

Copilot CLI local sandbox は user-level settings で管理し、未設定時の初回値だけを環境別に選ぶ。判断は [ADR-026](adr/026-copilot-cli-sandbox-environment-defaults-and-explicit-setting-preservation.md)、初回値と設定保持の手順は [`operations.md`](operations.md#copilot-local-sandbox-の既定値) を参照する。

`copilot-guardrails --allow-all` はツール権限の承認を省略するが、local sandbox の有効状態は変更しない。MCP と LSP は sandbox 対象外である。backend は macOS の Seatbelt、Linux、WSL、Codespaces、Dev Container の bubblewrap、Windows の ProcessContainer である。Linux 系の診断は `sandbox.enabled` が `true` または未設定の場合だけ bubblewrap を確認し、`false` の場合は probe を省略する。診断は利用可否を報告するものであり、sandbox 外での再実行方法が提示されることを保証しない。

コンテナ内でも利用者は `/sandbox enable` を実行できるが、このリポジトリの機能契約は有効化後の動作を保証しない。組織が enterprise の managed settings で sandbox を強制している場合は、組織管理設定が利用者設定より優先される。設定値は `home/.chezmoitemplates/copilot-user-settings.json`、環境別の初期値は設定同期スクリプトを正本とする。

## git pre-commit フック

gitleaks の pre-commit は、リポジトリ作成時に既定値を配るテンプレートフックと、リポジトリ内のフックとは別に動く設定ベースフックの二層で構成する。テンプレートフックは他のフック管理ツールへの影響をリポジトリ内へ限定し、設定ベースフックはリポジトリの作成時期やローカルフックの置換に依存しない走査を担う。両者の判断と保証範囲は [ADR-018](adr/018-git-hooks-via-init-templatedir.md) と [ADR-020](adr/020-git-hooks-via-config.md) を参照する。

二つの起動スクリプトは別ファイルとして管理し、走査ロジックの一致をテストで検査する。更新と確認は [`operations.md`](operations.md#git-pre-commit-フック)、症状別の復旧は [`troubleshooting.md`](troubleshooting.md#新規リポジトリに-gitleaks-pre-commit-hook-が入らない) を参照する。

## プラットフォーム検出

| 変数 | 説明 |
|------|------|
| `.chezmoi.os` | `linux`, `darwin`, `windows` |
| `.isLinux` / `.isMac` / `.isWindows` | 上から導出 |
| `.isWSL` | Linux かつ `kernel.osrelease` に `microsoft` を含む。Docker Desktop の WSL2 バックエンドで動くコンテナはホストの WSL カーネルを共有するため、この変数だけでは実 WSL と区別できない。区別が要る箇所では `/proc/sys/fs/binfmt_misc/WSLInterop` の存在を併せて確認する（ADR-012） |
| `.codespaces` / `.devcontainer` | Codespaces は `CODESPACES` で判定する。Dev Container は、VS Code の Dev Containers 拡張が Dotfiles セットアップへ渡す `REMOTE_CONTAINERS` で判定する。判定結果は chezmoi の初期化時に設定へ保存されるため、後続の統合ターミナルに同じ環境変数がなくても維持される |
| `.windowsUser` / `.corpUser` | 初回セットアップで入力する。入力を求めるのは stdin が TTY のときだけなので、非対話の `chezmoi init` では既存の設定値をそのまま引き継ぐ（引き継がないと空文字で上書きされ、`gitconfig-corp` の includeIf と ADR-012 の署名パスが壊れる） |

## プラットフォーム機能契約

プラットフォーム機能契約は、利用者向けの公開関数、alias、補完、ツール導入について、Windows/PowerShell、macOS/zsh、Linux/zsh、WSL/zsh の利用目的を等価に保つための分類である（ADR-019）。開発者は公開機能を変更するときに4環境の実装を更新するか、実装しない理由と適用範囲を契約と文書へ記録する。

`tests/test_platform_parity.py` は、公開シンボルが契約へ分類されていること、契約上の実装を示す設定断片が存在すること、共通ツールが両系統の install script に存在することを静的に検査する。この検査は各OS上でのコマンド実行結果や上流配布物の可用性までは保証しない。開発者は実機固有の動作を各環境で確認し、`review-repo` は契約、実装、CIの一致を点検する。

理由付き例外は次のとおりである。

- Windows の `e` は、Microsoft Edit を winget/DSC で管理する Windows 固有機能である（ADR-011）。`mise-self-upgrade` も winget 管理の mise を更新するため Windows 固有である
- Terraform は公式の PowerShell completion を提供していないため、補完はzshだけで提供する
- RadicleはWindows向け公式配布を確認できないため、`rad` の補完はzshだけで提供する
- bubblewrap は Linux と WSL の sandbox backend に必要である。macOS は Seatbelt、Windows は ProcessContainer を使うため導入しない

helm、gh、azd、trivy、kubectl、Azure CLIの補完はzshとPowerShellの両方で提供する。`fieldalignment` と `fast` は、Unix系とWindowsの両 install scriptで導入する。`gh-stack` は、公式 Copilot skill と GitHub CLI extension が未導入の場合だけ、OS別のセットアップスクリプトで全環境へ導入する。

`ghcd` の fzf preview は、zshでは `ls -la`、Windowsでは `cmd.exe` の `dir /a` を使う。コマンドは異なるが、選択候補のリポジトリにある隠し項目を含む一覧を表示する目的は等価である。

## Git `includeIf`

`home/dot_gitconfig.tmpl` はベース設定のみを置き、`includeIf` でプラットフォーム差分を切り替える: `gitdir:/home/` → Linux/WSL、`gitdir:/Users/` → macOS、`gitdir/i:C:/` 等 → Windows。WSL は Linux 側を読みつつ、`.isWSL` と WSL interop の有無で 1Password 連携パスを切り替える。

## コミット署名

1Password SSH エージェントで SSH 署名する。`gpg.ssh.program` は環境別: macOS `/Applications/1Password.app/.../op-ssh-sign`、Linux `/opt/1Password/op-ssh-sign`、WSL `~/.local/bin/op-ssh-sign-wrapper.sh`（ADR-012: `op-ssh-sign-wsl.exe` の CRLF 出力を補正）、Windows `C:/Users/<windowsUser>/.../op-ssh-sign.exe`。Dev Container / Codespaces では `commit.gpgsign = false`。

## PATH 管理（非対話シェル対応）

非対話シェル（Copilot CLI エージェント、IDE、スクリプト）では `.zshrc` / `$PROFILE` が読まれず、mise / brew 管理ツールが PATH から欠落する。対策として **POSIX 互換の `~/.profile` に共通 env を集約**し、各シェル起動ファイルから source する。

`~/.local/bin` は全プラットフォームで mise shims より前に置く。公式インストーラーが置いた実体（`uv` / `uvx` / `jq`）とベンダー実体への入口（`gh`）がここにあり、mise から外したツールの shim が端末に残っていても実体が勝つ必要があるためである。

| OS | 仕込み先 | 内容 |
|----|---------|------|
| Unix 共通 | `~/.profile` | brew shellenv、`GOPATH`、`~/go/bin` / `~/.cargo/bin` / mise shims / `~/.local/bin` をこの順で先頭へ移す（最後が最優先）。`__DOTFILES_PROFILE_LOADED` で再実行抑止 |
| Unix 共通 | `~/.zprofile` / `~/.zshenv` / `~/.bash_profile` / `~/.bashrc` | いずれも `~/.profile` を source（login / 非login / 対話 bash を網羅） |
| macOS のみ | `~/.local/bin/<tool>` への mise shim symlink | `run_onchange_after_21-link-mise-shims.sh` が自動生成 |
| Windows | ユーザー環境変数 `Path` | `run_once_after_05-setup-user-path` が `%USERPROFILE%\.local\bin`、`%LOCALAPPDATA%\mise\shims` の順に先頭へ置き、比較時は `\` を `/` へ正規化して大小文字を無視し重複を畳む |

### 各シェルの読み込み経路

`sh` / `bash(login)` は `.profile` を直接、`zsh(login)` は `.zprofile`、`zsh(非login)` は `.zshenv`、`bash(interactive non-login)` は `.bashrc` のみ読む。いずれからも `~/.profile` に誘導することで PATH が揃う。`bash -c` 等の非対話は親から env 継承する。

ただし macOS の login zsh では、並び順までは揃わない。`~/.zshenv` が `~/.profile` を読んだ後に `/etc/zprofile` が `path_helper` を実行し、`/etc/paths` に載るシステムディレクトリを先頭へ、それ以外を末尾へ移す。`~/.profile` は `__DOTFILES_PROFILE_LOADED` により再実行されないため、`~/.local/bin` や mise shims は `/usr/bin` より後ろに置かれたままになる。

`~/.zprofile` はこのうち `/opt/homebrew/opt/git/bin` だけを先頭へ戻す。gitleaks の設定ベースフックが git 2.54 以降を必要とするためである（ADR-020）。他のディレクトリを戻さないのは、システムツール全般を shadow したときの影響範囲を限定するためである。

### macOS GUI アプリ経由の PATH 注入

Dock / Spotlight / GitHub Desktop から起動された子プロセスは launchd 既定 PATH しか継承しない。特に **GitHub Desktop の Copilot SDK は `bash --norc --noprofile` で bash を spawn し、親が独自の hardcoded PATH を組む**ため、`.bashrc` / `BASH_ENV` / `launchctl setenv` では PATH 注入不可。唯一 **`~/.local/bin` だけは確実に含まれる**ため、mise 管理ツールは `run_onchange_after_21-link-mise-shims.sh` がそこへ symlink し、mise の管理外のツールは各導入スクリプトが実体か vendor 実体への symlink をそこへ置く。

- 言語ランタイム本体と実行可能な補助ファイルは除外する。対象はスクリプト内の `EXCLUDE_EXACT` / `EXCLUDE_PATTERN` を正本とする。Rust は mise の管理外であり、`cargo` / `rust` の shim は除外対象に含めない（ADR-016）
- 作成 symlink は state file (`${XDG_STATE_HOME}/chezmoi-dotfiles/mise-shim-links`) に記録され、管理対象だった symlink のみ自動掃除。手動で作ったものには触れない
- `~/.local/bin` に置く実体（`uv` / `uvx` / `jq`）と `gh` の symlink は各導入スクリプトが所有する。shim symlink とは名前が重ならず、重なった場合はスクリプトが既存を尊重して何もしない
- darwin 限定。Linux は `~/.profile` 経由、Windows は `run_once_after_05-setup-user-path` で解決済み

### mise の管理外にあるツール

GitHub CLI・jq・uv は mise の `[tools]` にも lockfile にも載せず、ツールごとの公式導入経路で導入する（ADR-028）。導入経路と更新手順は [`operations.md`](operations.md#ツールの管理境界) を参照する。

- **GitHub CLI**: 導入と更新は OS/ベンダーのパッケージマネージャーが所有する。`run_after_27-ensure-github-cli` は導入も複製もせず、POSIX では `~/.local/bin/gh` を vendor 実体への symlink として保ち、全プラットフォームで最小版を満たしているか検査して不足時に更新コマンドを案内する
- **jq**: `run_after_26-install-jq` が公式リリース asset を OS/CPU ごとに固定し、SHA-256 を検証してから `~/.local/bin/jq` へ置く。宣言に無い OS/CPU では別 CPU の asset へフォールバックせず、警告して何もしない
- **uv**: `run_after_25-install-uv` が版を含む固定 URL の公式インストーラーを取得し、SHA-256 を検証してから PATH 変更を無効化して実行する。展開先は `~/.local/bin` 配下の staging であり、版を確認してから `uv` と `uvx` を置き換える

いずれも導入済みの版が宣言と一致すればネットワークへ出ない。checksum または版の検証に失敗した場合は既存のバイナリを残す。

### mise shims の制約

mise は shims と `mise activate` を併用する。対話 zsh では `mise activate zsh` が shims を除去して自前挿入し、`[env]` / hooks が効く。非対話シェルでは shims のみで解決する。shims では `[env]` / `hooks` / `_.file` が動かないが、本 repo の `config.toml` は `[tools]` / `[settings]` のみ使用するため影響なし（必要時は `mise exec -- <cmd>`）。詳細: <https://mise.jdx.dev/dev-tools/shims.html>

### TypeScript language server の依存配置

mise の npm backend はパッケージごとにインストール先を分ける。`npm:typescript` の TypeScript 7.x は `tsc` の実行に使い、`npm:typescript-language-server` からは参照しない。language server が利用する `lib/tsserver.js` は、`run_after_22-install-typescript-lsp` が固定版の TypeScript 6.x を `~/.local/share/chezmoi-dotfiles/typescript-lsp` へ導入して提供する。スクリプトは mise 管理 Node と同じディレクトリの npm を使い、package version と `tsserver.js` が正しければ何もしない。不足または版違いの場合だけ再導入するため、初回適用で Node 導入を保留する Dev Container でも、`mise install` 後の次回適用で回復する。

Copilot CLI の `~/.copilot/lsp-config.json` は `initializationOptions.tsserver.path` で、この安定 prefix 配下の `node_modules/typescript/lib/tsserver.js` を指定する。mise の language server インストール先とバージョンをパスに含めないため、language server の更新後も設定は変わらない。LSP 用 TypeScript の版は `home/.chezmoidata.toml` を正本とする。

## MSVC リンカー解決 (Windows)

Windows で cargo が `windows-msvc` ターゲットをビルドするには MSVC の `link.exe` が必要（[ADR-017](adr/017-msvc-linker-env-var-override-windows.md)）。winget で導入する Coreutils for Windows の `link.exe`（ハードリンク作成コマンド）と名前が衝突し、Machine PATH 側が優先されるため PATH の並び替えでは解決できない。

- `reference/windows/configuration.dsc.yaml` で Visual Studio 2022 Build Tools + C++ ワークロード (`Microsoft.VisualStudio.Workload.VCTools`) を導入
- `run_onchange_after_20-resolve-msvc-linker.ps1` が `vswhere.exe` で現在の `link.exe` を解決し、ユーザー環境変数 `CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER` に設定する。PATH に依存しないため $PROFILE を読まないシェル（Copilot CLI 等）でも有効
- `{{ now }}` を script hash に埋め込み `chezmoi apply` の度に再評価するため、VS Build Tools の更新でツールセットのバージョンフォルダが変わっても追従する

## セットアップスクリプトの実行順

chezmoi は `run_*_before_*`、通常ファイル、`run_*_after_*` の順に適用し、同じフェーズではファイル名の番号順に実行する。全件一覧は変化しやすいため、gh-stack の導入と Git hook の確認を含む全実装は `home/run_*` を正本とする。

mise 関連では、本体を導入する `run_once_before_20-install-mise`、lockfile 変更を同期する `run_onchange_after_15-mise-sync-tools`、通常適用時にツールを導入する `run_once_after_20-mise-install`、macOS の shim symlink を更新する `run_onchange_after_21-link-mise-shims`、LSP 用 TypeScript を確認する `run_after_22-install-typescript-lsp` の依存関係を保つ。変更時は、mise 本体と設定の配置前に `mise install` を実行しないこと、LSP 用 TypeScript の導入前に Node が利用可能であること、Codespaces と Dev Container の分岐を壊さないことを確認する。

mise の管理外にある 3 つは `run_after_25-install-uv`、`run_after_26-install-jq`、`run_after_27-ensure-github-cli` が担当する。`uv` は `uv tool` を使う `run_once_after_30-install-tools` より前、`gh` の検査は `run_after_31-install-gh-stack` より前に置く。いずれも毎回の適用で走り、宣言と一致していれば何もしない。

`.ps1` スクリプトの実行系は `.chezmoi.toml.tmpl` の `[interpreters.ps1]` で `pwsh -NoLogo -NoProfile -File` に固定している（ADR-023）。プロファイルを読まないため、スクリプトは Machine+User の PATH に載るものだけに依存できる。プロファイル経由でしか PATH に入らないツールは使えない。
