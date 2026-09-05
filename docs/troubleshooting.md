# Troubleshooting

README に載せない復旧手順だけをまとめる。一般的な `chezmoi` / `mise` の仕様説明は各公式ドキュメントを参照。

## `warning: config file template has changed`

`.chezmoi.toml.tmpl` の更新後に出る。`chezmoi update` は設定を再生成しないため、`chezmoi init` を実行するまで毎回出続ける。

```bash
chezmoi init torumakabe
```

リポジトリ名を省略すると、ソースディレクトリが空になり `chezmoi update` が動かなくなる。必ず `torumakabe` を指定する。

`windowsUser` / `corpUser` の入力を求めるのは stdin が TTY のときだけだが、非対話で実行しても既存の設定値は引き継ぐ。値を変更したいときは対話シェルで実行する。

## `mise install` が部分失敗する

まず [`docs/operations.md`](operations.md#github-api-と-github_token) の手順で `GITHUB_TOKEN` を付けて再実行する。

### lockfile を再生成する

lockfile 側の問題なら再生成する。

```bash
mise ls --missing
rm ~/.config/mise/mise.lock
GITHUB_TOKEN=$(gh auth token) mise lock --global --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
mise install
```

## 直接導入したツールの導入に失敗する

### checksum 検証に失敗する

`checksum verification failed` は、取得物が `home/.chezmoidata.toml` のasset宣言と一致しないことを示す。.NETはSHA-512、その他の直接取得する配布物はSHA-256で確認する。この段階では既存の実体を変更しない。

宣言した版の公式checksumと `sha256` / `sha512` を照合する。一致していれば、通信経路による破損などを確認して `chezmoi apply` を再実行する。宣言が別の版の値を指していた場合は、版と取得元の対応を修正する。検証を省略したり、取得物から計算した値で宣言を上書きしたりしない。ツールごとの取得元は[運用手順](operations.md#mise-の管理外にあるツール)を参照する。

### Terraformの署名を確認できない

GPGが見つからない場合は、Linuxの `gnupg`、macOSのHomebrew `gnupg`、WindowsのGit同梱 `gpg.exe` の導入状態と実行パスを確認する。Windowsへ別のGnuPG packageを追加する構成にはしていない。

署名検証の失敗では、宣言した版に対応するchecksum list、signature、公開鍵、fingerprintの組合せを確認する。`GOODSIG` や「正しい署名」という表示だけでは受け入れず、終了コードと `VALIDSIG` のfingerprintを確認する。認証できなかった配布物は配置せず、署名確認を無効にして続行しない。

### Windows で直接導入した実体を置き換えられない

症状は `<tool> を置き換えられません。実行中のプロセスが掴んでいる可能性が
あります。` のようなエラーで `run_after_*.ps1` が失敗することである。対象の
実行ファイル（go.exe / node.exe / dotnet.exe / pnpm.exe / tsc.cmd /
typescript-language-server.cmd 等）を排他オープンできるか root の置き換え前
に確認する設計であり、失敗時は既存のインストールを変更しない。該当プロセス
（エディタの LSP、ターミナル上で動いている node/dotnet プロセスなど）を終了
してから `chezmoi apply` を再実行する。

### 版やCPU種別の不一致で直接導入が中断される

`expected <tool> <version>` のようなエラーは、候補の起動や版確認に失敗したことを示す。宣言した版、取得URL、アーカイブ内の選択対象、実際の終了コードを確認する。別版の混入や誤ったentrypointを修正し、検証を省略せず再適用する。

クラウド関連CLIでCPU種別の検証に失敗した場合は、OS/CPUに対応するassetを選んでいるか確認する。Windows arm64でx64版が起動できても、明示した互換実行の対象以外は受け入れない。

### クラウド関連CLIの既存ファイルが拒否される

既存の入口がscriptや別製品である場合、想定CPUと異なる場合、版やhelpから対象ツールと識別できない場合は、ダウンロード前に停止する。ファイルは変更しない。エラーに示されたパスの実体やリンク先、導入元を確認し、利用者のファイルを削除や上書きで回避しない。識別できる同じツールの実体なら、通常の再適用で宣言版へ更新できる。

### 直接導入が途中失敗した後の再適用

取得物はstagingで検証してから配置する。単体CLIの置換に失敗した場合は、通信やロックなどの原因を解消して再適用する。

SDKと複数entrypointの更新は一つの原子的操作ではない。途中失敗時はpayloadと入口の復旧を試み、復旧できなければエラーメッセージで回復用ファイルの場所を示す。回復用ディレクトリを先に削除せず、旧版を復旧してから再適用する。管理外の入口との衝突では既存ファイルを保持するため、その所有元を確認して配置方針を決める。

## Copilot sandbox が Linux で起動しない

`sandbox.enabled` が `true` または未設定で、shell command の実行に失敗する場合は、bubblewrap と user namespace を確認する。`false` の場合、`chezmoi apply` の診断はこの probe を省略する。

```bash
bwrap --version
cat /proc/sys/kernel/unprivileged_userns_clone 2>/dev/null
cat /proc/sys/user/max_user_namespaces 2>/dev/null
bwrap --unshare-user --uid 0 --gid 0 --ro-bind / / true
```

`bwrap` は 0.5.0 以上が必要である。sysctl が無効、または最小起動が失敗する場合は OS、WSL、container runtime の user namespace 設定を確認する。probe の失敗は bubblewrap を利用できないことを示すが、Codespaces と Dev Container の dotfiles 契約は初期値 `false` であるため、probe の成功を適用完了の条件にはしない。Copilot CLI が sandbox 外での再実行方法を提示するとは限らない。

## Copilot sandbox.enabled が意図した値にならない

初回値と設定保持の規則は [`operations.md`](operations.md#copilot-local-sandbox-の既定値) を参照し、user-level `~/.copilot/settings.json` の `sandbox.enabled` を確認する。

```bash
jq .sandbox.enabled ~/.copilot/settings.json
```

- `true` または `false`: 利用者設定の明示値として次回の `chezmoi apply` でも維持される
- `chezmoi apply` が `sandbox.enabled` の型に関するエラーで失敗する場合、既存の値が null や文字列など真偽値以外になっている。値を `true`/`false` に修正するか、キー自体を削除してから再実行する
- `/sandbox` の UI が managed もしくは locked と表示される場合、組織の enterprise managed-settings.json が sandbox を強制している。本リポジトリの chezmoi 設定はこの状態を作らないため、組織の IT 部門に確認する

本リポジトリの以前のブランチ（file-based managed settings 方式）を適用したことがある場合、Linux 系 `/etc/github-copilot/managed-settings.json`、macOS `/Library/Application Support/GitHubCopilot/managed-settings.json`、Windows `%ProgramFiles%\GitHubCopilot\managed-settings.json` が残っている可能性がある。組織が所有するファイルの可能性があるため自動削除しない。内容が本リポジトリ由来（`sandbox.enabled=true` の強制のみ等）と確認できた場合に限り、手動で削除するか組織の管理者に確認する。

## `mise.lock has changed since chezmoi last wrote it?` と聞かれる

`chezmoi status` が `MM .config/mise/mise.lock` を示し、`chezmoi apply` が上のプロンプトを出す。Codespaces のような TTY の無い環境では `could not open a new TTY` で停止する。

デプロイ済みの lockfile に、意図しないプラットフォームのエントリが加わった状態である。`chezmoi diff ~/.config/mise/mise.lock` で追加された行を確認する。`linux-x64-musl` や `windows-x64-baseline` のようなエントリが増えていれば、`lockfile_platforms` が効かないまま auto-lock が走ったことを意味する（[ADR-021](adr/021-mise-lockfile-platforms.md)）。

原因は二つある。まず mise のバージョンを確認する。

```bash
mise --version
```

`lockfile_platforms` は mise `2026.4.8` 以降が必要である。これより古い場合、設定は警告なく無視される。Homebrew formula 以外の mise がある端末では `run_once_before_20-install-mise.sh` がバージョンを問わず既存バイナリを保持するため、自分で更新する。

```text
macOS / Linux: mise self-update
Windows:       mise-self-upgrade
```

macOS の移行では、現在のシェルが Homebrew の絶対パスを含む activation hook を保持している可能性があるため、formula を自動削除しない。Homebrew 版の activation を読み込んだターミナルやシェルをすべて終了する。現在のシェルを継続して使う場合は、profile の再実行ガードを解除して login shell を起動し直す。

```bash
unset __DOTFILES_PROFILE_LOADED
exec zsh -l
```

新しいシェルで、`command -v mise` が導入スクリプトの案内したパスを返すことを確認して formula を削除する。新規に公式バイナリを配置した場合のパスは `~/.local/bin/mise` である。

```bash
command -v mise   # ~/.local/bin/mise
brew uninstall mise
```

formula をすでに削除し、`_mise_hook: no such file or directory: /opt/homebrew/bin/mise` が出る場合は、影響を受ける各シェルで公式バイナリの hook を読み直すか、そのシェルを終了する。

```bash
mise_path="$HOME/.local/bin/mise" # 導入スクリプトが別のパスを案内した場合は置き換える
eval "$("$mise_path" activate zsh)"
rehash
```

mise が要件を満たしていれば、原因は設定が届いていないことである。次で確認して配り直す。

```bash
mise settings get lockfile_platforms
chezmoi apply --force ~/.config/mise/config.toml
```

どちらの場合も、最後にデプロイ済み lockfile を source の内容へ戻す。`--force` を付けるのは、対象を lockfile 一つに限ってプロンプトを飛ばすためである。他のファイルのローカル変更には影響しない。

```bash
chezmoi apply --force ~/.config/mise/mise.lock
chezmoi status
```

`chezmoi status` から `.config/mise/mise.lock` が消えれば復旧している。

## `mise install` が `aube install failed: failed to resolve dependencies` で止まる

`npm:` バックエンドは mise 内蔵の [aube](https://aube.jdx.dev/) で install する。aube の `trustPolicy=no-downgrade` は、選んだ版より古い版が 1 つでも強い信頼証跡を持つ場合に install を止める。証跡は `approver`（staged publish） > `_npmUser.trustedPublisher` > `dist.attestations.provenance` の順にランク付けされる。

mise の表示は上記の一行に丸められるため、原因の判別には packument を直接見る。npm CLI は mise の shim 経由だと未導入ツールの自動 install を誘発して出力が汚れるので、node 同梱の実体を使う。

```bash
npm=$(dirname "$(mise which node)")/npm
for v in <古い版> <入らない版>; do
  echo "--- $v ---"
  "$npm" view "<pkg>@$v" _npmUser.trustedPublisher --json
  "$npm" view "<pkg>@$v" dist.attestations --json
done
```

古い版にだけ証跡があれば証跡後退である。まず上流の公開経路が変わったのかを確認する（リリース workflow の差分、公開者）。変わっていなければレジストリ側で剥がれている。利用中の npm レジストリプロキシは `dist.integrity` / `signatures` / `attestations` を全バージョンで落とし、`_npmUser.trustedPublisher` の保持もバージョンによってばらつく。

対処は `trust_policy_excludes` をバージョン指定で足す。

```toml
[tools]
"npm:some-tool" = { version = "latest", trust_policy_excludes = ["some-tool@1.2.3"] }
```

パッケージ名だけを書くと将来版も一括で除外され、本物の証跡後退に気づけなくなる。`npm.shell_out=true` は mise の信頼検証を全パッケージで外すため使わない。

## shell 起動時に `mise WARN missing:` が出る

`mise upgrade` 等で `~/.config/mise/mise.lock` が更新された後、対応する `mise install` / `mise reshim` が走っていないと shim と install marker が古いまま残り、`mise hook-env` で `WARN missing:` が出る。

通常は `chezmoi apply` で `run_onchange_after_15-mise-sync-tools` フック（[ADR-013](adr/013-mise-lockfile-sync-hook.md)）が自動で同期する。手動で `mise uninstall` した等のケースで残った場合は次を実行する。

```bash
mise install
mise reshim
```

## TypeScript language server が TypeScript を発見できない

Copilot CLI の起動ログに `Could not find a valid TypeScript installation` が出る場合、安定 prefix に LSP 用 TypeScript が導入されているか確認する。`tsc --version` の成功は、別の mise インストール先にあるコンパイラーを確認するだけであり、language server の依存解決を保証しない。

設定と導入スクリプトを配布すると、`run_after_22-install-typescript-lsp` が直接導入した Node.js に同梱された npm で LSP 用 TypeScript を確認し、不足または版違いの場合だけ導入する。

```powershell
chezmoi apply
$lspTypeScriptRoot = Join-Path $HOME '.local\share\chezmoi-dotfiles\typescript-lsp'
Test-Path (Join-Path $lspTypeScriptRoot 'node_modules\typescript\lib\tsserver.js')
tsc --version
$typescriptPackage = Join-Path $lspTypeScriptRoot 'node_modules\typescript\package.json'
(Get-Content $typescriptPackage -Raw | ConvertFrom-Json).version
```

macOS、Linux、WSL では同じ確認を POSIX シェルで実行する。

```bash
chezmoi apply
lsp_typescript_root="$HOME/.local/share/chezmoi-dotfiles/typescript-lsp"
test -f "$lsp_typescript_root/node_modules/typescript/lib/tsserver.js"
tsc --version
node -p "require('$lsp_typescript_root/node_modules/typescript/package.json').version"
```

`tsc` がコンパイラー用 TypeScript 7.x、安定 prefix の `package.json` が LSP 用 TypeScript 6.x を返すことを確認する。その後 Copilot CLI を通常どおり再起動し、起動ログの `Using Typescript version` が安定 prefix の `tsserver.js` を示すことと、`typescript language server ready` を確認する。最後に実際の `.ts` ファイルで定義参照とシンボル検索を実行する。`/lsp test` は stdio を閉じて終了させる経路があるため、この復旧の完了判定には使用しない。

## `run_once_*` スクリプトの warning / error

実行順と役割は [`docs/architecture.md`](architecture.md#セットアップスクリプトの実行順) を参照。

- **warning で継続**: shell 設定の一部、`mise install` 後の任意ツール、追加ツール導入の失敗
- **error で停止**: Oh My Zsh の clone、Docker 本体導入など継続に必要な処理

warning は標準エラーに表示される。表示されたコマンドを手動で再実行して復旧する。

## GitHub API または `gh extension install` が SAML 403 で失敗する

次のエラーは、GitHub CLI が使用する OAuth token に対象 organization の SAML SSO 承認がない場合に発生する。

```text
Resource protected by organization SAML enforcement.
You must grant your OAuth token access to this organization.
```

ブラウザーで `https://github.com/orgs/<organization>/sso` を開いて SSO を完了し、同じ環境で GitHub CLI を再認証する。

```bash
gh auth refresh --hostname github.com
gh api repos/<organization>/<repository>/releases/latest
chezmoi apply
```

Windows と WSL は通常、GitHub CLI の認証情報を別々に保持する。一方で解決しても他方には反映されないため、それぞれで再認証する。WSL からブラウザーを起動できない場合は、表示された URL を Windows のブラウザーで開く。

## `run_once_*` スクリプトが sudo を要求して停止する

Codespaces 以外ではパッケージ導入に sudo が必要である。パスワードを入力するか、sudoers を設定する。

## Dev Container で mise ツールが入っていない

コンテナ作成時は `mise install` を自動実行しない。README の Dev Container セクション、または [`docs/operations.md`](operations.md#github-api-と-github_token) の手順で起動後に実行する。

## Dev Container から npm registry へ接続できない

このリポジトリは、ホストの npm 設定をコンテナへ自動継承しない。公式レジストリへの接続に失敗した場合は、まずコンテナ内で現在の設定を確認する。

```bash
npm config get registry
```

組織がレジストリを指定している場合だけ、管理者から提示された URL を設定する。

```bash
npm config set registry '<管理者指定の registry URL>'
```

ホストのトークン、認証情報を含む `.npmrc`、その他の資格情報をコンテナへコピーしない。認証が必要な場合は、管理者が定めたコンテナ向けの認証手順を使う。

## 非対話シェルで PATH が通らない

症状: Copilot CLI エージェント、IDE タスク、`bash script.sh` から `copilot` / `uv` / `kubectl` / `azd` が `command not found`。

設計の全体像は [`docs/architecture.md`](architecture.md#path-管理非対話シェル対応) を参照。復旧は以下を試す:

- **Unix**: `chezmoi apply` で `~/.profile` 系が配置されているか確認。新規 login シェル（新しい Terminal タブ）で有効化
- **macOS GUI アプリ経由**（GitHub Desktop の Copilot SDK 等）: `chezmoi apply` で `run_onchange_after_21-link-mise-shims.sh` が走り、残っている mise 管理ツール（kubectl・lefthook・helm・terraform 等）の shim が `~/.local/bin` に symlink される。Copilot CLI を再起動すれば反映（除外リストの変更は `home/run_onchange_after_21-link-mise-shims.sh.tmpl` で編集）。
  - Go、Node.js、.NET SDK、Bun、pnpm、TypeScript CLI、typescript-language-server、typescript-lsp (`tsserver`) は shim-link の対象ではない。各導入スクリプトが主要コマンド (`go`/`gofmt`、`node`/`npm`/`npx`、`dotnet`/`dnx`、`bun`/`bunx`、`pnpm`、`tsc`、`typescript-language-server`、`tsserver`) への入口を `~/.local/bin` に置くため、POSIX (macOS/Linux/WSL) では `bash --norc --noprofile` のような非対話 shell からもコマンド名で解決できる。リンクだけが欠損し payload が完全な場合は、`chezmoi apply` の再実行で再ダウンロードせずに復旧する
- **Windows**: `run_once_after_05-setup-user-path.ps1` は、`%USERPROFILE%\.local\bin`、Go、Node.js、.NET SDK、pnpm、三つの TypeScript 用ディレクトリ、残存する mise shims の順でユーザー環境変数 `Path` の先頭へ登録する。完全な一覧は [`operations.md`](operations.md#mise-の管理外にあるツール) を参照する。`chezmoi apply` を再実行して登録内容を直す。既存プロセスは変更前の環境変数を保持するため、ターミナルを開き直す。GUI アプリへ反映されない場合は、サインアウトまたは OS の再起動後に確認する。`pwsh -NoProfile` は PowerShell Profile を読まないが、親プロセスから継承したユーザー `Path` は削除しない

それでも反映されないときは state を消して再実行:

```bash
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

確認コマンド:

```bash
echo "$PATH" | tr ':' '\n'   # ~/.local/bin が ~/.local/share/mise/shims より前にあること
command -v copilot uv jq gh
```

```powershell
(Get-Command uv).Source
[Environment]::GetEnvironmentVariable('Path', 'User') -split ';' | Select-Object -First 10
```

`uv` / `jq` / `gh` が mise shims の側に解決される場合は、`~/.local/bin` が先に来ていない。上の state 削除と `chezmoi apply` で並びを入れ直す。

## jq のダウンロードに失敗する

`failed to download` で `chezmoi apply` が停止する。既存の jq は変更されず、未導入の場合は未導入のままとなる。宣言版と asset の URL、ネットワークやプロキシの状態を確認し、復旧後に `chezmoi apply` を再実行する。

## `uv` / `jq` の導入が checksum またはバージョン検証で失敗する

症状: `chezmoi apply` が `error: checksum verification failed for ...` または `error: expected jq <version> but ...` / `error: expected uv <version> but ...` で停止する。

`~/.local/bin` 配下の staging で検証しているため、既存の `uv` / `uvx` / `jq` はそのまま残っている。取得物を信頼できないので、スクリプトは異常終了する。

1. `home/.chezmoidata.toml` の `jq.version` / `uv.version` と、対応する SHA-256 が上流の公式リリースと一致するか確認する
2. jq は各リリースの `sha256sum.txt`、uv はリリース asset の `uv-installer.sh` / `uv-installer.ps1` を正本とする
3. 一致していれば、ネットワーク経路（プロキシや企業 TLS 検査）が成果物を書き換えていないか確認する
4. 宣言を直したら `chezmoi apply` を実行する。`run_once` の state 削除は不要である

版の検証で失敗した場合は、宣言した版と実際に取得された版がずれている。asset のファイル名と SHA-256 が同じ版を指しているか確認する。

## Windows で `uv.exe` / `jq.exe` を置き換えられない

症状: `chezmoi apply` が `uv.exe を置き換えられません。実行中のプロセスが掴んでいる可能性があります。` で停止する。

Windows は実行中の `.exe` を置き換えられない。既存のバイナリは変更していない。

1. `uv` / `jq` を使っているプロセスを終了する。Copilot CLI の command hook は `uv run` で起動するため、Copilot CLI のセッションも閉じる
2. 掴んでいるプロセスを探す

    ```powershell
    Get-Process | Where-Object { $_.Path -like "$HOME\.local\bin\*" } | Format-Table Name, Id, Path
    ```

3. `chezmoi apply` を再実行する

## Windows で `cargo build` / `cargo check` がリンクエラーになる (`link.exe` が見つからない/引数エラー)

症状: `error: linking with \`link.exe\` failed` や、coreutils の `link` コマンドのヘルプ/エラーメッセージがそのまま出力される。

原因: winget で導入した Coreutils for Windows の `link.exe`（ハードリンク作成コマンド）が Machine PATH に登録されており、MSVC の `link.exe` と名前が衝突する。詳細は [`docs/architecture.md`](architecture.md#msvc-リンカー解決-windows) と [ADR-017](adr/017-msvc-linker-env-var-override-windows.md)。

復旧:

1. Visual Studio 2022 Build Tools（C++ によるデスクトップ開発ワークロード）が未導入なら、管理者権限の PowerShell で `winget configure -f reference\windows\configuration.dsc.yaml` を実行する
2. `chezmoi apply` を実行する（`run_onchange_after_20-resolve-msvc-linker.ps1` は毎回再評価されるため、追加の手動操作は不要）
3. 環境変数が設定されているか確認する（新しいシェルで反映される）

    ```powershell
    [Environment]::GetEnvironmentVariable('CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER', 'User')
    ```

## 新規リポジトリに gitleaks pre-commit hook が入らない

新規/backfill 済みリポジトリの hook は、`git init`/`git clone` 時に `~/.config/git/templates/hooks/pre-commit` から `.git/hooks/pre-commit` へコピーされる（ADR-018）。テンプレートが未配置なら次で復旧する。

```bash
git config --global init.templateDir   # 期待値: ~/.config/git/templates
chezmoi apply ~/.config/git/templates/hooks/pre-commit
```

`init.templateDir` は `git init`/`git clone` した瞬間にしか `.git/hooks/` へコピーされない。既存リポジトリに hook が無い場合は `git -C <repo> init` を再実行して backfill する（既存ファイルは上書きされないため安全）。`git-hooks-audit` / `Invoke-GitHooksAudit` で ghq 管理下の全リポジトリの hook 有無をまとめて確認できる。

Windows で hook が存在するのに同じエラーが出る場合、`/usr/bin/env bash` が WSL の `bash.exe` を拾い、Windows 形式の `C:/...` パスを開けていない可能性がある。この pre-commit hook はその経路を避けるため POSIX `sh` 互換で管理する。mise の Windows shim も extensionless 版は `/bin/bash` スクリプトなので、hook 内では `gitleaks.exe` を優先する。

## 設定ベースフックが全リポジトリで動いていない

Git 2.54 以降なら、`.git/hooks/pre-commit` の有無に関わらず設定ベースフックが走る（ADR-020）。有効かどうかは `chezmoi apply` のたびに確認され、無効なら原因ごとに案内を変えた警告が出る。

```bash
git hook list --show-scope pre-commit   # 期待値: global<TAB>dotfiles-gitleaks
git --version
```

git が 2.54 以降なら、原因は git ではなく設定の欠落である。

```bash
git config --global --get-regexp '^hook\.dotfiles-gitleaks\.'   # 何も返さなければ設定が届いていない
chezmoi apply ~/.gitconfig
```

git が 2.54 より前なら更新する。

```bash
brew install git                                    # macOS
sudo add-apt-repository -y ppa:git-core/ppa \
  && sudo apt-get update && sudo apt-get install -y git   # Linux / WSL
winget upgrade --id Git.Git                         # Windows
```

macOS では新しい login shell で `git --version` が 2.54 以降になることを確認する。`/etc/zprofile` の `path_helper` が PATH を並べ替えるため、`~/.zprofile` が `/opt/homebrew/opt/git/bin` を先頭へ戻している（[`architecture.md`](architecture.md#各シェルの読み込み経路)）。

Linux で apt を実行しても `git --version` が変わらない場合は、より前の PATH にある別の実体が新しい git を隠している。Codespaces と Dev Container のベースイメージは git をソースビルドして `/usr/local/bin` へ入れるため、この状態になる。`chezmoi apply` の bootstrap はこの二つの環境でだけ張り替える。手動で直す場合は、対象が確かにベースイメージのビルドであることを先に確かめる。

```bash
command -v git                       # /usr/local/bin/git が返るか確認
test -L /usr/local/bin/git           # symlink なら誰かが張り替えた後なので触らない
/usr/bin/git --version               # apt 側が 2.54 以降か確認
sudo ln -sfn /usr/bin/git /usr/local/bin/git
```

`command -v git` が `/usr/local/bin/git` 以外を返す場合や、すでに symlink である場合は、mise の shim や利用者自身のビルドである可能性がある。張り替える前に、その git の出所と PATH の並びを確認する。

## commit が gitleaks-pre-commit not found で拒否される

設定ベースフックには `$GIT_DIR/hooks` のような存在確認が無く、`command` が実行できないと commit が失敗する（ADR-020）。`chezmoi apply` の中断などで `~/.local/bin/gitleaks-pre-commit` が未配置になった場合に起きる。

```bash
chezmoi apply ~/.local/bin/gitleaks-pre-commit
```

## Codespaces / Dev Container で `copilot` のバージョンが古い

症状: `copilot --version` が極端に古い（例: 1.0.3）。

原因: ベースイメージ（Codespaces universal 等）に `/usr/local/bin/copilot` が同梱されており、`run_once_before_10-install-packages.sh` の導入判定が `command -v copilot` だと、これを検出して公式スクリプトによる導入をスキップしていた。同梱バイナリはイメージのビルド時点で固定されるため、`copilot update` の対象にもならない。

対策は導入済み。判定は `~/.local/bin/copilot` の実体で行う。既存のコンテナでは [`run_once_*` の再実行](operations.md#run_once_-の再実行)により固定した公式リリースアーカイブを導入し、次を確認する。

```bash
exec zsh -l
type -a copilot                                   # 先頭が ~/.local/bin/copilot であること
~/.local/bin/copilot --version
```

同梱バイナリは削除しない。`~/.local/bin` が PATH で `/usr/local/bin` より前にあれば shadow されるため、特権操作なしで解決する（Codespaces universal イメージではこの順序を確認済み。逆順のイメージでは PATH 側の調整が必要）。`copilot update` が更新するのは実行された側の実体だけで、同梱バイナリは対象外である。

VS Code 拡張 (`github.copilot-chat`) が PATH へ注入する `.../globalStorage/github.copilot-chat/copilotCli/copilot` は shim であり、自分のディレクトリを除いた PATH から実体を探して委譲するだけなので、バージョン固定の原因にはならない。ただし `command -v copilot` はこの shim を返すため、確認には `type -a copilot` を使う。

## Copilot CLI: preToolUse フックが並列実行時にすり抜ける

症状: 短時間に複数のツール呼び出しが走った際、`copilot-guard.py` / `uv-enforcer.py` の deny が適用されず、ブロックすべき操作が実行される。

原因 (CLI v1.0.35 系で観測):

- **タイムアウト時の挙動は fail-open**: `timeoutSec` を超えても hook プロセスは kill されず、CLI 側が待機を打ち切って allow フォールバックし、遅れて届く deny は破棄される
- **hook 起動が逐次キュー化**: 同時に 5 件のツール呼び出しが来ても hook は 1.5〜4 秒間隔で順番に起動される。並列数が増えるほどキュー末尾が `timeoutSec` を超え、上記 fail-open が発動しやすい

対策 (本リポジトリで適用済み):

- `home/private_dot_copilot/hooks/hooks.json` の `timeoutSec` を引き上げ、キューが長くなっても fail-open に落ちにくくする（現在値は同ファイルを参照）
- 上流の挙動変更を追跡する (`github/copilot-cli` の issue)

暫定回避:

- 高並列が予想される作業（一括コマンド送信など）では、1 応答内のツール呼び出し数を抑える
- deny すべき操作が通ってしまった場合は `~/.copilot/audit.jsonl`（成功ログ）/ `audit-denies.jsonl`（preToolUse deny）/ `audit-failures.jsonl`（tool handler error）で事後検出し、手動で巻き戻す

## Copilot CLI: `hook errored` の詳細を確認する

`preToolUse` command Hook が非ゼロで終了すると、Copilot CLI はツール呼び出しを拒否する。ツール結果には `hook errored` だけが表示される場合でも、セッションの `events.jsonl` に Hook の標準エラーが記録されている。

```powershell
Get-Content "$HOME\.copilot\session-state\<session-id>\events.jsonl" |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Where-Object {
    $_.type -eq 'hook.end' -and
    $_.data.hookType -eq 'preToolUse' -and
    $_.data.success -eq $false
  } |
  ForEach-Object { $_.data.error.message }
```

`hook errored` だけから Hook 本体の障害と判断しない。標準エラー、Hook の起動コマンド、起動時に解決された runtime を確認する。

本リポジトリの command hook は `~/.local/bin/uv` の `uv run` で起動する。`uv` は mise の管理外にあり、shim もバージョン解決も挟まない。標準エラーに mise のインストールログが出る場合は、`~/.copilot/hooks/hooks.json` と PATH の並びが最新か確認し、`chezmoi apply` で配り直す。

上のフィルターで何も表示されない場合は、CLI の更新でイベント形式が変わった可能性がある。`Where-Object { $_.type -eq 'hook.end' }` まで条件を緩め、直近イベントの `data` 全体を確認する。
