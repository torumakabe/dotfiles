# Architecture Guide

README から分離した、構成と設計判断の詳細である。運用手順は [`docs/operations.md`](operations.md) を参照。

## ディレクトリ構造

```text
home/                           ← chezmoi source
├── .chezmoi.toml.tmpl          ← 共通 flag・変数定義
├── .chezmoiignore              ← 条件付き除外
├── .chezmoiremove              ← 不要ファイルの削除
├── dot_gitconfig*.tmpl         ← Git 設定
├── dot_zshrc.tmpl              ← 対話 zsh
├── dot_profile.tmpl            ← 共通 env（PATH, brew shellenv, mise env）
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

- 設定配布 `chezmoi` / ツール版管理 `mise` / Python 実行 `uv`
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
各 command hook は host 上で `uv run ...` を実行する。PowerShell も同じ引数を使う。hook の cwd と標準入力はそのまま渡し、runtime の親 PATH から uv の実体を直接起動する。mise による導入と更新は host 側で行い、通常の sandbox shell 内では実行しない。

Copilot CLI local sandbox は user-level settings で管理し、未設定時の初回値だけを環境別に選ぶ。判断は [ADR-026](adr/026-copilot-cli-sandbox-environment-defaults-and-explicit-setting-preservation.md)、初回値と設定保持の手順は [`operations.md`](operations.md#copilot-local-sandbox-の既定値) を参照する。

`copilot-guardrails --allow-all` はツール権限の承認を省略するが、local sandbox の有効状態は変更しない。MCP と LSP は sandbox 対象外である。backend は macOS の Seatbelt、Linux、WSL、Codespaces、Dev Container の bubblewrap、Windows の ProcessContainer である。Linux 系の診断は `sandbox.enabled` が `true` または未設定の場合だけ bubblewrap を確認し、`false` の場合は probe を省略する。診断は利用可否を報告するものであり、sandbox 外での再実行方法が提示されることを保証しない。

sandbox の developer-tool 自動許可は、`PATH` に含まれる各ディレクトリを読み取り対象にするが、その中のシンボリックリンクが指す親ディレクトリ全体までは許可しない。Node.js の `corepack` と `npx`、npm backend の `tsc`、`installs` の外に実体を置く `core:dotnet` などを実行できるよう、mise data root を `sandbox.userPolicy.filesystem.readonlyPaths` へ追加する。`MISE_INSTALLS_DIR` がdata rootの外を指す場合は、そのディレクトリも追加する。同期スクリプトは対象ディレクトリを作成してから設定を書き込み、存在しないread-only grantによるsandbox起動失敗を防ぐ。書き込みは許可しない。

Copilot runtime 1.0.83 は利用者の uv cache を read-only で自動許可するが、通常の `uv run` も cache 内へ一時ファイルと lock を作成する。同じ path を `readwritePaths` へ追加しても自動 read-only grant が残るため、preToolUse hook の `uv-enforcer.py` が shell command に Copilot 専用の `UV_CACHE_DIR` を追加する。設定同期はその専用 directory だけを `readwritePaths` へ追加し、親に read-only または deny の設定がある場合と、管理対象が symbolic link または reparse point の場合は停止する。host の uv cache、cache home 全体、mise data root には write grant を与えない。

この契約の対象は、Copilot CLI が profile を読まずに起動する built-in shell の直接実行である。利用者が `bash -lc`、`zsh -c`、profile を読む `pwsh` などを明示的に起動すると、各 shell の初期化処理が sandbox 内で mise を再実行する場合がある。これは継承済みの実体 `PATH` を使う通常実行とは別に検証する。

コンテナ内でも利用者は `/sandbox enable` を実行できるが、このリポジトリの機能契約は有効化後の動作を保証しない。Dev Container と Codespaces のツールは、通常の Linux と同じ mise config、lockfile、導入スクリプト、更新手順で管理する。Dev Container は作成時の GitHub 未認証を避けるため、同じ config と lockfile を使う `mise install --yes` だけを起動後に実行する。組織が enterprise の managed settings で sandbox を強制している場合は、組織管理設定が利用者設定より優先される。設定値は `home/.chezmoitemplates/copilot-user-settings.json`、環境別の初期値は設定同期スクリプトを正本とする。

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

| OS | 仕込み先 | 内容 |
|----|---------|------|
| Unix 共通 | `~/.profile` | brew shellenv、`GOPATH`、`~/.local/bin` / `~/go/bin` / `~/.cargo/bin`、公式 `mise env --shell bash` による実体 PATH と SDK 環境 |
| Unix 共通 | `~/.zprofile` / `~/.zshenv` / `~/.bash_profile` / `~/.bashrc` | いずれも `~/.profile` を source（login / 非login / 対話 bash を網羅） |
| macOS のみ | `~/.local/bin/<tool>` への mise shim symlink | 既存の GUI 用登録を保持。実際の利用への影響を確認してから撤去する |
| Windows | PowerShell profile とユーザー環境変数 `Path` | 既存の `mise activate pwsh` が実体環境を子へ渡す。User PATH の shim 登録は保持 |

### 各シェルの読み込み経路

`sh` / `bash(login)` は `.profile` を直接、`zsh(login)` は `.zprofile`、`zsh(非login)` は `.zshenv`、`bash(interactive non-login)` は `.bashrc` のみ読む。いずれからも `~/.profile` に誘導することで PATH が揃う。`bash -c` 等の非対話は親から env 継承する。

`__DOTFILES_PROFILE_LOADED` は Homebrew とユーザー bin の初期化だけを抑止する。mise の環境生成に成功した後の PATH は、export した `__DOTFILES_MISE_PATH` に保持する。再度 profile を読んだ時点の PATH と異なる場合だけ環境を再生成する。同じ PATH を継承した子では mise を呼ばない。この値はプロセス環境だけに保持し、版付き PATH の一覧をファイルへ保存しない。環境生成に失敗した場合は stderr に通知し、成功時の値を更新しない。

macOS の login zsh では、`~/.zshenv` の後に `/etc/zprofile` の `path_helper` が PATH を並べ替える。`~/.zprofile` は `/opt/homebrew/opt/git/bin` を優先させてから共有 profile を読み、mise の実体 PATH を再構成する。Git の処理は、設定ベースフックが git 2.54 以降を必要とするためである（ADR-020）。対話 activation がない非対話 login zsh でも同じ構成を使う。

対話 zsh と PowerShell は公式の `mise activate` を維持し、ディレクトリ移動時の版切替を利用できるようにする。共通設定の `activate_shims = false` により、full activation は shim farm を PATH へ追加しない。`activate_aggressive = true` は、OS や他のパッケージ管理ツールが提供する同名コマンドより mise の実体 PATH を前方に保つ。対話シェルと、そこから起動する Copilot CLI は、同じ実体 PATH を使う。Windows のユーザー PATH に登録する shim は非対話環境との互換性のため残るため、実体 PATH の契約は PowerShell profile を読み込んだターミナルから Copilot CLI を起動する場合に適用する。

### Copilot の通常 shell と command hook

Copilot CLI 1.0.81 以降の Unix の通常 agent shell は、host 上で非対話 login bash の環境を取得し、親環境へ merge してから sandbox shell を作る。共有 profile の `mise env` はこの host 側で実行され、通常の agent command shell は `--norc --noprofile` で実体環境を使う。環境取得時の cwd は HOME なので、project-local の版切替はこの構成の保証に含めない。Linux の初回導入には、この機能を含む CLI 1.0.83 を使う。

command hook はこの環境補完を共有せず、runtime の親環境を使う。各 hook は、その親 PATH にある uv の実体を `uv run` で直接起動する。SDK の `session.shell.exec` も通常 agent shell の補完を共有しない別 API である。利用未確認の API への対応は要求せず、実際に使う CLI／GUI の起動と最初の hook を区別して確認する。

この区分の根拠は [runtime bd85d404 の環境取得](https://github.com/github/copilot-agent-runtime/blob/bd85d40405b59a8f2088da47f7a1e833f7291624/src/runtime/src/tools/session_shell_driver.rs#L594-L620) と [hook の親環境](https://github.com/github/copilot-agent-runtime/blob/bd85d40405b59a8f2088da47f7a1e833f7291624/src/runtime/src/session/services/hook_processor_service.rs#L468-L477) である。GUI 同梱 runtime の版と起動環境は、PATH 上の単体 CLI とは別に扱う。公式 `.github/github-app.yml` に汎用 PATH 注入項目は確認できず、setup script の export で親アプリを変更する構成にはしない。

### 残している shim 登録

macOS の `run_onchange_after_21-link-mise-shims.sh` は、以前の GUI 固定 PATH 対策として `~/.local/bin` に shim をリンクする（ADR-002）。言語ランタイム等の除外対象はスクリプトの `EXCLUDE_EXACT` / `EXCLUDE_PATTERN` で定義し、自作リンクだけを `${XDG_STATE_HOME:-~/.local/state}/chezmoi-dotfiles/mise-shim-links` で管理する。Windows では `run_once_after_05` が User PATH に shim ディレクトリを登録する。

これらの登録と `mise reshim` は残すが、共有 profile は shim ディレクトリを追加しない。実際に使う CLI／GUI、hook、非対話起動での依存を確認する前に登録を削除しない。撤去と復元の対象は [運用手順](operations.md#実体環境への切替) を参照する。shim が存在することと、通常実行が shim を選ぶことは区別する。

### uv の実体配置

uv は全対象 OS で mise の `aqua:astral-sh/uv` backend を使う。Windows ARM64 では、lockfile が指定する x64 配布物を従来どおりエミュレーションで使う。独自 wrapper、常設 updater、PATH 同期処理は追加しない。

`mise env` または既存の `mise activate` が設定した実体 PATH を使うと、aqua backend の uv/uvx を直接解決できる。shim と実体 PATH は別の仕組みであり、この設定は shim の全面撤去ではない。macOS の shim symlink と Windows の User PATH は上記のとおり保持する。通常の sandbox shell が使う Copilot 専用 uv cache だけは ADR-030 に従って書き込みを許可する。

lock は `latest` を要求として保持し、uv 0.12.10 の単一 entry に5対象プラットフォームの配布物と checksum、provenance を固定する。

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

`.ps1` スクリプトの実行系は `.chezmoi.toml.tmpl` の `[interpreters.ps1]` で `pwsh -NoLogo -NoProfile -File` に固定している（ADR-023）。プロファイルを読まないため、スクリプトは Machine+User の PATH に載るものだけに依存できる。プロファイル経由でしか PATH に入らないツールは使えない。
