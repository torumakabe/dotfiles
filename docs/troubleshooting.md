# Troubleshooting

README に載せない復旧手順だけをまとめる。一般的な `chezmoi` の仕様説明は公式ドキュメントを参照。

## `warning: config file template has changed`

`.chezmoi.toml.tmpl` の更新後に出る。`chezmoi update` は設定を再生成しないため、`chezmoi init` を実行するまで毎回出続ける。

```bash
chezmoi init torumakabe
```

リポジトリ名を省略すると、ソースディレクトリが空になり `chezmoi update` が動かなくなる。必ず `torumakabe` を指定する。

`windowsUser` / `corpUser` の入力を求めるのは stdin が TTY のときだけだが、非対話で実行しても既存の設定値は引き継ぐ。値を変更したいときは対話シェルで実行する。

## OS package版CLIの入口を作成できない

最低版やCPU種別の検査に失敗した場合は、HomebrewまたはWinGetが所有する実体を確認する。PATH上の別のコピーが同じ版を返しても、導入済みとは扱わない。packageが不足している場合は、そのpackageだけをmanagerで修復して再適用する。全scriptの実行記録を消す必要はない。

Windowsではユーザーpackageの所有aliasとその参照先を確認する。machine scopeのpackageや他の場所の実体へ勝手に切り替えない。native symlinkの作成に失敗した場合は、既存DSCのDeveloper Mode設定と対象ディレクトリの権限を確認する。独自wrapperやファイルコピーで置き換えない。

`~/.local/bin` の管理外ファイルやリンクと衝突した場合、スクリプトはそれを保持する。所有元を確認せずに削除しない。packageの実体が適合していれば、入口が欠けている場合だけ `chezmoi apply` で無通信の修復ができる。

## 直接導入したツールの導入に失敗する

### checksum 検証に失敗する

`checksum verification failed` は、取得物が `home/.chezmoidata.toml` のasset宣言と一致しないことを示す。.NETはSHA-512、その他の直接取得する配布物はSHA-256で確認する。この段階では既存の実体を変更しない。

宣言した版の公式checksumと `sha256` / `sha512` を照合する。一致していれば、通信経路による破損などを確認して `chezmoi apply` を再実行する。宣言が別の版の値を指していた場合は、版と取得元の対応を修正する。検証を省略したり、取得物から計算した値で宣言を上書きしたりしない。ツールごとの取得元は[運用手順](operations.md#ツールごとの導入経路)を参照する。

### Terraformの署名を確認できない

GPGが見つからない場合は、Linuxの `gnupg`、macOSのHomebrew `gnupg`、WindowsのGit同梱 `gpg.exe` の導入状態と実行パスを確認する。Windowsへ別のGnuPG packageを追加する構成にはしていない。

署名検証の失敗では、宣言した版に対応するchecksum list、signature、公開鍵、fingerprintの組合せを確認する。`GOODSIG` や「正しい署名」という表示だけでは受け入れず、終了コードと `VALIDSIG` のfingerprintを確認する。認証できなかった配布物は配置せず、署名確認を無効にして続行しない。

### 1Password CLIの署名を確認できない

1Password CLIで署名確認に失敗した場合は、固定版ZIPのhashと `op.exe` のAuthenticode結果を確認する。署名が有効でも、subject、issuer、固有EKUが宣言と異なれば配置しない。版を変えるだけで検証を通したり、署名確認を省略したりしない。Linuxのapt repositoryや鍵の衝突も、既存設定の所有元を確認してから解消する。

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

クラウド関連CLIやワークステーションCLIでCPU種別の検証に失敗した場合は、OS/CPUに対応するassetを選んでいるか確認する。Windows arm64でx64版が起動できても、明示した互換実行の対象以外は受け入れない。

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

## TypeScript language server が TypeScript を発見できない

Copilot CLI の起動ログに `Could not find a valid TypeScript installation` が出る場合、安定 prefix に LSP 用 TypeScript が導入されているか確認する。`tsc --version` の成功は、コンパイラー用 TypeScript の確認に限られ、language server の依存解決を保証しない。

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

- **warning で継続**: shell 設定の一部、任意ツール、追加ツール導入の失敗
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
- **macOS GUI アプリ経由**（GitHub Desktop の Copilot SDK 等）: 個別の導入スクリプトが `~/.local/bin` へ実体またはnative symlinkを配置する。欠損した入口は `chezmoi apply` で復旧し、その後にCopilot CLIを再起動する。実体が適合していればリンクの修復に再ダウンロードは不要である。OS packageが最低版未満の場合は、[OS packageの障害](#os-package版cliの入口を作成できない)を参照する
- **Windows**: `run_once_after_05-setup-user-path.ps1` は、`%USERPROFILE%\.local\bin`、Go、Node.js、.NET SDK、pnpm、三つの TypeScript 用ディレクトリをユーザー環境変数 `Path` の先頭へ登録する。完全な一覧は [`operations.md`](operations.md#ツールごとの導入経路) を参照する。既存プロセスは変更前の環境変数を保持するため、ターミナルを開き直す。GUI アプリへ反映されない場合は、サインアウトまたは OS の再起動後に確認する。`pwsh -NoProfile` は PowerShell Profile を読まないが、親プロセスから継承したユーザー `Path` は削除しない

PATH登録スクリプトが既に成功扱いで、登録だけを修復する場合は、[個別のrun_once再実行手順](operations.md#run_once_-の再実行)で対象keyだけを扱う。`scriptState` 全体は削除しない。

確認コマンド:

```bash
echo "$PATH" | tr ':' '\n'   # ~/.local/bin が含まれること
command -v copilot uv jq gh
```

```powershell
(Get-Command uv).Source
[Environment]::GetEnvironmentVariable('Path', 'User') -split ';' | Select-Object -First 10
```

現行構成が mise を必要としないことは、新規シェルで上のコマンドが管理対象の入口を返すかによって確認する。既存プロセスや端末に残る旧状態の扱いと、清掃済み確認を別作業にする理由は[ワークアラウンド](../.github/copilot-instructions.md#ワークアラウンド定期チェック対象)を参照する。

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

Windows で hook が存在するのに同じエラーが出る場合、`/usr/bin/env bash` が WSL の `bash.exe` を拾い、Windows 形式の `C:/...` パスを開けていない可能性がある。この pre-commit hook はその経路を避けるため POSIX `sh` 互換で管理する。gitleaks は `~/.local/bin/gitleaks.exe`、WinGet の入口、PATH 上の実体の順に解決する。見つからない場合は警告して走査を省略し、解決した gitleaks の走査が失敗した場合は commit を拒否する。

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

`command -v git` が `/usr/local/bin/git` 以外を返す場合や、すでに symlink である場合は、利用者自身のビルドや別の管理元である可能性がある。張り替える前に、その git の出所と PATH の並びを確認する。

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

本リポジトリの command hook は `~/.local/bin/uv` の `uv run` で起動し、ツール管理機構による shim やバージョン解決を挟まない。`~/.copilot/hooks/hooks.json` の起動コマンドが異なる場合は、`chezmoi apply` で配り直す。

上のフィルターで何も表示されない場合は、CLI の更新でイベント形式が変わった可能性がある。`Where-Object { $_.type -eq 'hook.end' }` まで条件を緩め、直近イベントの `data` 全体を確認する。
