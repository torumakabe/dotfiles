# Copilot CLI local sandbox 実機検証

## 目的

この文書は、検証対象のリモートブランチを WSL2、macOS、Codespaces、Dev Container へ取得し、Copilot CLI local sandbox の設定と backend を各環境内で確認する手順を定める。

Windows ホストから `wsl.exe` やコンテナ操作でコマンドを起動した結果は、PATH、TTY、ログインシェル、対話入力が実際の利用時と異なる場合がある。Copilot CLI のスラッシュコマンドと sandbox 内のコマンド実行は、対象環境の対話ターミナルで確認する。

## 検証対象

| 環境 | `sandbox.enabled` が未設定の場合の期待値 | 追加の確認 |
|---|---|---|
| WSL2 | `true` | WSL version、user namespace |
| macOS | `true` | macOS version、CPU architecture |
| Codespaces | `false` | Codespace image、user namespace |
| Dev Container | `false` | container image、実行ユーザー、user namespace |

WSL1 は対象外とする。Windows native の ProcessContainer は Windows 側の検証で扱う。

## リモートブランチを取得する

検証対象ブランチを環境変数へ設定する。Stacked PR の場合は、検証対象の変更をすべて含む最上位ブランチを指定する。

```bash
export TEST_BRANCH='<検証対象ブランチ>'
```

新規環境で`install.sh`から初回導入全体を検証する場合は、同じbranchを`CHEZMOI_INIT_BRANCH`へ渡す。未設定時の`install.sh`はリポジトリの既定branchを使用する。

```bash
CHEZMOI_INIT_BRANCH="${TEST_BRANCH}" ./install.sh
```

chezmoi のソースリポジトリへ移動する。

```bash
repo_root="$(git -C "$(chezmoi source-path)" rev-parse --show-toplevel)"
cd "${repo_root}"
git status --short
```

未コミットの変更がある場合はここで止め、退避または別環境で検証する。クリーンな場合だけブランチを取得する。

```bash
git fetch origin
git switch "${TEST_BRANCH}" 2>/dev/null ||
  git switch --track "origin/${TEST_BRANCH}"
git pull --ff-only origin "${TEST_BRANCH}"
git rev-parse HEAD
```

以降の結果には `git rev-parse HEAD` の値を記録する。

## 前提ツールを確認する

```bash
uname -a
command -v git
command -v chezmoi
command -v uv
command -v copilot
command -v jq
copilot --version
chezmoi --version
mise --version
mise ls --missing
repo_root="$(git rev-parse --show-toplevel)"
chezmoi --source "${repo_root}/home" diff \
  ~/.config/mise/config.toml \
  ~/.config/mise/mise.lock
```

`mise ls --missing` と `chezmoi diff` の結果を記録する。検証環境の導入版が lockfile と異なる場合は、その差を結果表へ残す。コマンドが不足している場合は、その環境の初期構築手順に従う。検証のためだけに異なる導入方法を追加すると、dotfiles が提供する構成を確認できないため、場当たり的なインストールは行わない。

## 自動テストを実行する

まず sandbox に関係するテストを実行する。

```bash
uv run python -m unittest \
  tests.test_copilot_sandbox_config \
  tests.test_copilot_bubblewrap \
  tests.test_platform_parity \
  -v
```

続けて全テストを実行する。

```bash
uv run python -m unittest discover -s tests
git diff --check
```

テストによる設定変更は一時ディレクトリへ隔離される。実ユーザーの `~/.copilot/settings.json` をテスト用データで置き換えない。

## 設定同期を隔離して確認する

この確認は、実ユーザーの設定を変更せず、レンダリング済み POSIX スクリプトが `sandbox.enabled=false` を保持することを検査する。

```bash
repo_root="$(git rev-parse --show-toplevel)"
test_root="${repo_root}/.sandbox-verification-work"
test ! -e "${test_root}"
rendered="${test_root}/configure-sandbox.sh"
mkdir -p "${test_root}/copilot"
printf '%s\n' '{"sandbox":{"enabled":false}}' \
  >"${test_root}/copilot/settings.json"

case "$(uname -s)" in
  Darwin) chezmoi_os='darwin' ;;
  Linux) chezmoi_os='linux' ;;
  *) echo 'Unsupported OS for this verification' >&2; exit 1 ;;
esac

case "$(uname -m)" in
  x86_64) chezmoi_arch='amd64' ;;
  arm64|aarch64) chezmoi_arch='arm64' ;;
  *) echo 'Unsupported architecture for this verification' >&2; exit 1 ;;
esac

chezmoi --source "${repo_root}/home" execute-template \
  --override-data "{\"chezmoi\":{\"os\":\"${chezmoi_os}\",\"arch\":\"${chezmoi_arch}\"}}" \
  --file "${repo_root}/home/run_onchange_after_35-configure-copilot-sandbox.sh.tmpl" \
  >"${rendered}"

COPILOT_HOME="${test_root}/copilot" bash "${rendered}"
jq -e '.sandbox.enabled == false' "${test_root}/copilot/settings.json"
case "$(uname -s)" in
  Darwin)
    test "$(stat -f '%Lp' "${test_root}/copilot/settings.json")" = '600'
    ;;
  Linux)
    test "$(stat -c '%a' "${test_root}/copilot/settings.json")" = '600'
    ;;
esac
rm -rf "${test_root}"
```

## dotfiles を適用する

差分を確認してから適用する。

```bash
repo_root="$(git rev-parse --show-toplevel)"
chezmoi --source "${repo_root}/home" diff
chezmoi --source "${repo_root}/home" apply
```

Linux 系では `sandbox.enabled` が `true` または未設定の場合に bubblewrap 診断が実行される。`false` の場合は probe を省略する。warning が出た場合は、後述の確認結果とともに記録する。

## Copilot CLI の対話動作を確認する

### 初期状態

対象環境の対話ターミナルで Copilot CLI を起動する。

```bash
copilot
```

`/sandbox` を実行する。複数タブの TUI で General、Auth、Filesystem、Network を順に開き、各画面を確認する。

```text
/sandbox
```

確認項目は次のとおり。

- General に表示される sandbox の有効状態が環境別の期待値と一致する
- Auth、Filesystem、Network の各画面を開ける
- backend 名が表示される版では、その表示を記録する
- MCP と LSP は sandbox 対象外である

backend 名が表示されない版では「表示なし」と記録し、成功条件にはしない。managed または locked と表示される場合は、組織管理設定が利用者設定より優先されているため、環境別の初期値との不一致を dotfiles の失敗とは扱わない。

### boolean 値の維持

通常の macOS、Linux、WSL では、手動無効化後の `false` が維持されることを確認する。Windows native は Windows 側の検証で同じ契約を確認する。

Copilot CLI で次を実行する。

```text
/sandbox disable
```

Copilot CLI を終了し、利用者設定を確認する。

```bash
jq -e '.sandbox.enabled == false' ~/.copilot/settings.json
```

Copilot CLI を再起動して `/sandbox` を実行し、無効状態が持続していることを確認する。

### chezmoi 適用後の持続

Copilot CLI を終了し、次を実行する。

```bash
repo_root="$(git rev-parse --show-toplevel)"
chezmoi --source "${repo_root}/home" apply
jq -e '.sandbox.enabled == false' ~/.copilot/settings.json
```

Copilot CLI を再起動し、`/sandbox` が無効を示すことを確認する。これにより、dotfiles 適用が利用者の選択を上書きしないことを確認できる。

Codespaces と Dev Container では初期値 `false` を確認した後、`/sandbox enable` を実行する。Copilot CLI を終了して同じ `chezmoi --source "${repo_root}/home" apply` を実行し、`sandbox.enabled=true` が維持されることを確認する。この確認は boolean 値を維持する dotfiles 契約を対象とし、有効化した sandbox の互換性確認とは分けて記録する。

### 手動有効化の互換性調査

Copilot CLI で次を実行する。

```text
/sandbox enable
```

Copilot CLI を終了し、設定を確認する。

```bash
jq -e '.sandbox.enabled == true' ~/.copilot/settings.json
```

再起動後に `/sandbox` の各タブと shell command の実行結果を確認する。Codespaces と Dev Container での結果は互換性調査として記録し、dotfiles 契約の合否には含めない。

## bubblewrap の利用可否を確認する

WSL2、Codespaces、Dev Container では、対象環境のターミナルで次を実行する。

```bash
bwrap --version
cat /proc/sys/kernel/unprivileged_userns_clone 2>/dev/null || true
cat /proc/sys/user/max_user_namespaces 2>/dev/null || true
bwrap --unshare-user --uid 0 --gid 0 --ro-bind / / true
```

バージョン、sysctl の値、最小起動の終了コードを記録する。probe は bubblewrap の利用可否を把握するためのものであり、成功を dotfiles 契約の合格条件にはしない。Copilot CLI で shell command を実行した場合は、その結果を記録する。sandbox 外での再実行方法が提示されることは前提にしない。

## 環境別の補足

### WSL2

Windows 側で WSL2 であることを確認する。

```powershell
wsl.exe -l -v
```

残りの検証は Windows から `wsl.exe -d ... -- <command>` で代行せず、対象ディストリビューションの対話ターミナル内で実行する。特に Copilot CLI のスラッシュコマンド、ログインシェルの PATH、TTY を使う sudo、bubblewrap 内のコマンド実行はホストからの非対話起動だけでは確認済みと扱わない。

### macOS

```bash
sw_vers
uname -m
```

`/sandbox` の各タブを確認する。Seatbelt と表示される場合は記録し、表示されない版では「表示なし」とする。bubblewrap の確認は不要である。

### Codespaces

Codespace の統合ターミナルで実行する。

```bash
printf 'CODESPACES=%s\n' "${CODESPACES:-}"
printf 'CODESPACE_NAME=%s\n' "${CODESPACE_NAME:-}"
cat /etc/os-release
```

初期値は `false` である。組織管理設定が値を強制している場合は、その表示と値を記録する。Codespace のベースイメージ更新によって user namespace の可否が変わり得るため、過去の結果を流用せず probe を毎回実行する。

### Dev Container

Dev Container の統合ターミナルで実行する。

```bash
cat /etc/os-release
id
printf 'REMOTE_CONTAINERS=%s\n' "${REMOTE_CONTAINERS:-}"
chezmoi data | jq '{codespaces, devcontainer}'
```

VS Code の Dev Containers 拡張は Dotfiles セットアップへ `REMOTE_CONTAINERS=true` を渡し、chezmoi は初期化時の判定結果を設定へ保存する。統合ターミナルでは `REMOTE_CONTAINERS` が空の場合があるため、`chezmoi data` の `.devcontainer` も確認する。必要に応じて「Dev Containers: Show Container Log」を開き、Dotfiles セットアップコマンドに `--remote-env REMOTE_CONTAINERS=true` が含まれることを確認する。ログ全体にはパスなどの環境固有情報が含まれるため、記録には判定に必要な引数だけを残す。

初期値は `false` だが、組織管理設定が値を強制している場合は、その表示と値を記録する。container runtime、security option、実行ユーザーによって user namespace の可否が変わる。ホスト側での `docker exec` の成功だけでは Copilot CLI の対話利用を確認済みと扱わない。

## 結果を記録する

環境ごとに次の表をコピーして記入する。

| 項目 | 結果 |
|---|---|
| 検証日 | |
| 環境 | WSL2 / macOS / Codespaces / Dev Container |
| OS または image、architecture | |
| commit SHA | |
| Copilot CLI version | |
| chezmoi version | |
| mise version、同期状態 | |
| lockfile との差 | なし / 差の内容 |
| 自動テスト | 成功 / 失敗 |
| 初期 `sandbox.enabled` | `true` / `false` / 組織管理値 |
| `/sandbox` General/Auth/Filesystem/Network | 確認結果 |
| backend 表示 | 表示値 / 表示なし |
| boolean 値の維持 | 成功 / 失敗 / 組織管理のため対象外 |
| 手動 enable の互換性 | 成功 / 失敗 / 未実施 / 対象外 |
| bubblewrap version | macOS は N/A |
| user namespace probe | 終了コード。macOS は N/A |
| warning またはエラー | |

失敗時は、実行コマンド、終了コード、標準エラー、`/sandbox` の各画面の表示を残す。認証情報や機密性のある環境変数の値は記録へ含めない。

## ADR-030 の撤去判定

Copilot CLI または MXC の更新後は、issue の状態や版番号だけで ADR-030 の回避策を撤去しない。sandbox を有効にした新規 Copilot CLI セッションで、hook が設定した `UV_CACHE_DIR` を同じ tool call 内で解除し、uv の既定 cache を使う操作が成功するか確認する。

Bash tool では次を実行する。

```bash
env -u UV_CACHE_DIR uv run --no-project -- python --version
```

PowerShell tool では次を実行する。

```powershell
$env:UV_CACHE_DIR = $null
uv run --no-project -- python --version
```

終了コード0で Python の version が表示された場合、その環境では専用 cache を使わずに通常の `uv run` が動作している。撤去時点で Copilot local sandbox を利用している管理対象の Windows、macOS、Linux、WSL2 端末すべてで個別に成功した場合に限り、`.github/copilot-instructions.md` に列挙した ADR-030 の実装を一括して撤去する。一つでも失敗した場合は回避策を維持し、終了コードと標準エラーを検証記録へ残す。

| 環境 | 専用 cache 適用後 | 撤去判定プローブ |
|---|---|---|
| WSL2 | 成功 | 成功 |
| macOS | 成功 | 成功 |
| 通常の Linux | 対象端末なし | 対象端末なし |
| Windows ProcessContainer | 成功 | 失敗。回避策を維持 |

## 検証記録

変化しやすい実測値は、この表へ追記する。環境内の対話確認を実施していない結果は、dotfiles 契約の合格として扱わない。

| 検証日 | 環境と確認方法 | OS、architecture | Copilot CLI | chezmoi | mise 同期 | bwrap | 結果 |
|---|---|---|---|---|---|---|---|
| 2026-08-16 | macOS、対話ターミナルと自動テスト | macOS 26.6.1、arm64 | 1.0.81-0 | 2.70.0 | 2026.8.6、成功 | N/A | 全368テストが成功し、27テストをskip。初期値は`true`。`/sandbox`のGeneral、Auth、Filesystem、Networkを確認し、手動enableとdisableの値が再起動後も維持された。backend名の表示はなかった |
| 2026-08-16 | Dev Container、対話ターミナルでの互換性調査 | Ubuntu 26.04、arm64 | 1.0.80 | 未記録 | npmミラーの一時設定後に成功 | 0.11.1、probe失敗 | Dev Containers 0.88.0のログで、Dotfilesセットアップへ`--remote-env REMOTE_CONTAINERS=true`が渡されることを確認した。bubblewrapはインストール済みだが、user namespace作成が`No permissions to create a new namespace`で失敗した。Copilot CLIのshell commandも同じ理由で失敗した。現行契約では初期値を`false`とし、この互換性調査を合否条件に含めない |
| 2026-08-16 | Codespaces、commit `1ec7eee`で隔離した設定ディレクトリを使用 | Linux 6.8.0-1052-azure、x86_64 | 実体の配置を確認。version取得は未完了 | 2.72.0 | miseとuvが未導入のため未実施 | 未導入 | `CODESPACES=true`を検出し、初期値`false`、ファイルモード`600`、既存boolean値の維持を確認した。`~/.copilot/settings.json`は未作成で、`/sandbox`と自動テストは未実施 |
| 2026-08-16 | WSL2、対話ターミナルと自動テスト | Ubuntu 22.04.5、x86_64、kernel 6.18.35.2-microsoft-standard-WSL2 | version未記録 | version未記録 | 未記録 | 0.6.1、probe成功 | 対象33テストが成功し、4テストをskip。全363テストが成功し、18テストをskip。隔離した設定同期、`chezmoi apply`、手動enableとdisableの値が再起動後と再適用後も維持されることを確認した。backend名の表示はなかった |
| 2026-08-16 | Windows native | Windows build 26200、architecture 未記録 | 1.0.81-0 | 未記録 | 未確認 | N/A | 単体テストと WinGet Configuration 構文は成功。対話的な enable、disable は未実施 |
| 2026-09-11 | Windows native、profile 読み込み済み PowerShell 7.6.5 から WinGet 本体を起動し、built-in PowerShell で直接確認 | build、architecture 未記録 | 1.0.83 | 未記録 | host の実体 PATH を sandbox が保持 | N/A | host の `copilot` alias は `%LOCALAPPDATA%\Microsoft\WinGet\Links\copilot.exe` を指した。sandbox 内で `uv`、`uvx`、`node`、`npm`、`npx`、`corepack`、`tsc`、`dotnet`、`jq` はすべて mise 実体へ解決し、各 `--version` が終了コード0で成功した。shim は実体 PATH 群より後ろだった。sandbox 内の `LOCALAPPDATA` はパッケージ配下へリダイレクトされた。新しい read-only grant の適用、profile を読む子 shell、GUI または profile なしの起動、5 hook 全体の確認は未実施 |
| 2026-09-11 | WSL2、新規Copilot CLIセッションのbuilt-in Bashへ検証scriptを直接渡して確認 | OS、architecture未記録 | 1.0.83 | 未記録 | commit `78f8937`のmise read-only grantを適用 | 未記録 | manifestの43コマンドはすべて期待するmise実体へ解決した。`uv`、`uvx`、`node`、`npm`、`npx`、`corepack`、`tsc`、`dotnet`、`jq`の実行は終了コード0だった。`uv run --no-project -- python --version`は`~/.cache/uv/.tmp...`への一時ファイル作成がread-only filesystemで失敗し、単独tool callでも同じ終了コード2となった。ADR-030のuv cache write grant適用後の再検証は未実施 |
| 2026-09-11 | WSL2、commit `0c35b02` 適用後の新規Copilot CLIセッションでbuilt-in Bashへ検証scriptを直接渡して確認 | OS、architecture未記録 | 1.0.83 | 未記録 | Copilot専用uv cacheのread-write grantとcommand内`UV_CACHE_DIR`を適用 | 未記録 | `UV_CACHE_DIR`は`/home/tomakabe/.cache/github-copilot/uv`だった。manifestの43コマンドは不一致0で、`uv`、`uvx`、`jq`、`node`、`npm`、`corepack`、`npx`、`tsc`、`typescript-language-server`はすべて期待するmise実体から終了コード0で実行された。`uv run --no-project -- python --version`はPython 3.10.12を返して終了コード0で成功し、command hookエラーは発生しなかった |
| 2026-09-11 | macOS、commit `6a88175` 適用後の新規Copilot CLIセッションでbuilt-in Bashを使用 | macOS 26.6.2、arm64 | 1.0.84-4 | 未記録 | Copilot専用uv cacheのread-write grantとcommand内`UV_CACHE_DIR`を適用 | N/A | `UV_CACHE_DIR`は`/Users/tomakabe/Library/Caches/github-copilot/uv`、`uv`はmise管理下の0.12.10だった。専用cacheを使う`uv run --no-project -- python --version`はPython 3.14.6を返して終了コード0で成功した。同じtool call内で`UV_CACHE_DIR`を解除した撤去判定プローブもPython 3.14.6を返して終了コード0で成功し、command hookエラーは発生しなかった |
| 2026-09-11 | Windows native、commit `7ef5d73` 適用後の新規Copilot CLIセッションでbuilt-in PowerShellを使用 | build、architecture未記録 | version未記録 | 未記録 | Copilot専用uv cacheのread-write grantとcommand内`UV_CACHE_DIR`を適用 | N/A | `UV_CACHE_DIR`は`C:\Users\tomakabe\AppData\Local\GitHubCopilot\uv`、`uv`はmise管理下の0.12.10だった。専用cacheを使う`uv run --no-project -- python --version`はPython 3.14.5を返して成功した。専用cacheを解除した撤去判定プローブはAppContainer配下のuv cacheへの一時ファイル保存をアクセス拒否されて失敗したため、回避策を維持する。適用時のPowerShell wrapperはnative commandの失敗をtool callの終了コードへ反映せず、両tool callが終了コード0と報告された。子PowerShellで終了コードを維持する修正版の再検証は未実施 |
| 2026-09-11 | Windows native、commit `417b22f` 適用後の新規Copilot CLIセッションでbuilt-in PowerShellを使用 | build、architecture未記録 | version未記録 | 未記録 | Copilot専用uv cacheのread-write grant、command内`UV_CACHE_DIR`、子PowerShellによる終了コード伝播を適用 | N/A | `UV_CACHE_DIR`は`C:\Users\tomakabe\AppData\Local\GitHubCopilot\uv`、`uv`はmise管理下の0.12.10だった。専用cacheを使う`uv run --no-project -- python --version`はPython 3.14.5を返し、tool callは終了コード0で成功した。専用cacheを解除した撤去判定プローブはAppContainer配下のuv cacheへの一時ファイル保存をアクセス拒否され、tool callは終了コード1を返した。標準エラーは通常のtextで、両方の実行にcommand hookエラーはなかったため、Windowsでは回避策を維持する |
| 2026-09-11 | WSL2、新規Copilot CLIセッションのbuilt-in Bashで撤去判定プローブを実行 | OS、architecture未記録 | version未記録 | 未記録 | commit `0c35b02` のCopilot専用uv cache回避策を適用済み | 未記録 | `env -u UV_CACHE_DIR uv run --no-project -- python --version`はPython 3.10.12を返し、tool callは終了コード0で成功した。標準エラーとcommand hookエラーは発生しなかった |
| 2026-09-11 | Dev Container、Docker 29.7.2から非対話検証。commit `89fbd06`を基点に本変更を適用 | Ubuntu 26.04.1 LTS、arm64 | 1.0.83 | 2.72.0 | mise 2026.9.4。npm registry proxyを設定して30ツールを導入し、missing 0 | 0.11.1、probe失敗 | `devcontainer=true`、`codespaces=false`、初期`sandbox.enabled=false`を確認した。uv 0.12.10、Python 3.14.4、Node.js 24.20.0、TypeScript 7.0.2、typescript-language-server 6.0.0はmise実体から実行できた。公式Linux ARM64 archiveのSHA-256検証を含む初回mise導入と全479テストが成功した。導入済み状態での`mise install --yes`はlockfileを変更しなかった。初回の実ツール導入時に生じたauto-lock差分は`chezmoi apply --force ~/.config/mise/mise.lock`で復旧した。user namespace probeは権限不足で終了コード1となった。Copilot CLIの対話画面は未確認であり、dotfilesのsandbox契約の合格とは扱わない |
| 2026-09-11 | Codespaces、GUIで新規作成した2-core環境の統合ターミナルでcommit `875f49e`を確認 | Linux、x86_64。OS詳細未記録 | version未記録 | 2.72.0 | mise 2026.9.4、missing 0 | 未確認 | 回復後の構成確認であり、初回導入の通し成功ではない。最初の`install.sh`はchezmoi取得中に停止し、`CHEZMOI_INSTALL_ONLY=1`で再実行した。最初の`chezmoi init --apply`は終了コード130となり、再実行で完了した。さらに、Codespaceの認証tokenが公開`github/gh-stack`へのAPI要求をSAML enforcementにより拒否したため、一時的な資格情報なしの`GH_CONFIG_DIR`で公式`gh`コマンドを手動再実行した。回復後は`sandbox.enabled=false`と`activate_shims=false`を維持し、gh 2.100.0、uv 0.12.10、Python 3.14.4、Node.js 24.20.0、TypeScript 7.0.2、typescript-language-server 6.0.0をmise実体から実行できた。全自動テストと`git diff --check`は成功した。初回導入の合否、Copilot CLIの対話画面、user namespace probeは未確認である |
