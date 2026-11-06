# Copilot CLI local sandbox 実機検証

## 目的

この文書は、検証対象のリモートブランチを Linux、WSL2、macOS、Windows、Codespaces、Dev Container へ取得し、Copilot CLI local sandbox の設定と backend を各環境内で確認する手順を定める。

Windows ホストから `wsl.exe` やコンテナ操作でコマンドを起動した結果は、PATH、TTY、ログインシェル、対話入力が実際の利用時と異なる場合がある。Copilot CLI のスラッシュコマンドと sandbox 内のコマンド実行は、対象環境の対話ターミナルで確認する。

## 検証対象

| 環境 | `sandbox.enabled` が未設定の場合の期待値 | 追加の確認 |
|---|---|---|
| Linux | `true` | distribution、user namespace |
| WSL2 | `true` | WSL version、user namespace |
| macOS | `true` | macOS version、CPU architecture |
| Windows | `true` | Windows version、ProcessContainer |
| Codespaces | `false` | Codespace image、user namespace |
| Dev Container | `false` | container image、実行ユーザー、user namespace |

WSL1 は対象外とする。Windows native は後述の専用手順に従う。

## リモートブランチを取得する

以下は Linux、WSL2、macOS、Codespaces、Dev Container 用の手順である。Windows native では[専用手順](#windows-native-で移行処理を確認する)を使う。

検証対象ブランチを環境変数へ設定する。Stacked PR の場合は、検証対象の変更をすべて含む最上位ブランチを指定する。

```bash
export TEST_BRANCH='<検証対象ブランチ>'
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

## dotfiles を適用する

差分を確認してから適用する。

```bash
repo_root="$(git rev-parse --show-toplevel)"
chezmoi --source "${repo_root}/home" diff
chezmoi --source "${repo_root}/home" apply
```

Linux 系では `sandbox.enabled` が `true` または未設定の場合に bubblewrap 診断が実行される。`false` の場合は probe を省略する。warning が出た場合は、後述の確認結果とともに記録する。

## 実 CLI で uv と sandbox 設定を確認する

対象環境の通常のシェルで、使用する Python を sandbox 外に用意し、保存先を確認する。

```bash
uv python dir
uv python find --managed-python
```

`UV_PYTHON_INSTALL_DIR` を使う場合は、その値を設定して `chezmoi apply` した環境から Copilot CLI を起動する。新しい Copilot CLI セッションの sandbox 内で、次を実行する。

```bash
uv run --no-project --managed-python python -c "import sys; print(sys.version); print(sys.executable)"
```

各環境で、次を確認する。

- 実行が成功し、表示された interpreter が `uv python dir` の保存先またはその実体に属する
- `readonlyPaths` に同じ保存先があり、保存先がリンクの場合はその実体も含まれる
- 通常の shell tool で mise 管理コマンドが実行できる
- CLI 起動環境で `UV_CACHE_DIR` を設定していない場合、uv の既定 cache が `readwritePaths` に含まれ、別の tool call から同じ cache を再利用できる
- 旧フックのファイルと、最初の移行時に旧フック専用の `~/.copilot/hooks` 読み取り許可が削除される。その他の利用者設定と監査ログは保持される

一回限りの probe はリポジトリへ追加しない。検証用の marker と一時ファイルは終了時に削除する。Cloud sandbox の Python 自動導入は local sandbox とは別に確認する。

## Copilot CLI の対話動作を確認する

uv の書き込み許可は、通常の `uv cache dir` と sandbox 内の出力を比較し、`uv run` 後にホスト側へファイルが残ることまで確認する。`/sandbox policy` の表示だけでは成功と扱わない。プロジェクト固有のキャッシュ設定がある場合は、ユーザー共通設定との差も記録する。

`tests.test_copilot_sandbox_config` は設定生成と filesystem access control を検査する。Copilot CLI を使った確認は実機検証手順に従う。

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
- `sandboxMcpServers` が有効、`sandboxLspServers` が無効である。sandbox 有効時はローカル MCP server が sandbox 内で実行される

ローカル MCP の資格情報 masking は、合成変数を用いた比較で確認した。CLI と条件ごとの結果、実際の資格情報を測定していない制約は [ADR-035](adr/035-copilot-cli-sandbox-mcp-servers.md) を参照する。

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

## Windows native で移行処理を確認する

Windows の PowerShell で検証対象ブランチを設定し、chezmoi のソースリポジトリの変更を確認する。

```powershell
$testBranch = '<検証対象ブランチ>'
$sourcePath = chezmoi source-path
if ($LASTEXITCODE -ne 0) { throw 'chezmoi source-path failed' }
$repoRoot = git -C $sourcePath rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) { throw 'git rev-parse failed' }
Set-Location -LiteralPath $repoRoot
git status --short
```

未コミットの変更がある場合はここで止め、退避または別環境で検証する。クリーンな場合だけブランチを取得し、commit SHA を記録する。

```powershell
git fetch origin
if ($LASTEXITCODE -ne 0) { throw 'git fetch failed' }
git switch $testBranch
if ($LASTEXITCODE -ne 0) {
  git switch --track "origin/$testBranch"
  if ($LASTEXITCODE -ne 0) { throw 'git switch failed' }
}
git pull --ff-only origin $testBranch
if ($LASTEXITCODE -ne 0) { throw 'git pull failed' }
git rev-parse HEAD
```

取得したリポジトリで sandbox 関連テストと全単体テストを実行する。

```powershell
uv run -m unittest tests.test_copilot_sandbox_config tests.test_copilot_bubblewrap tests.test_platform_parity -v
if ($LASTEXITCODE -ne 0) { throw 'sandbox tests failed' }
uv run -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw 'unit tests failed' }
git diff --check
```

使用する Python が導入済みであることと、適用する差分を確認する。`UV_PYTHON_INSTALL_DIR` を使う場合は、その値を設定した PowerShell で実行する。

```powershell
uv python dir
uv python find --managed-python
chezmoi --source (Join-Path $repoRoot 'home') diff
```

差分を確認してから、同じ PowerShell で適用する。

```powershell
chezmoi --source (Join-Path $repoRoot 'home') apply
```

適用後、Copilot CLI の `readonlyPaths` に `uv python dir` の保存先があり、保存先が reparse point の場合はリンク先も含まれることを確認する。初回移行で旧フック専用の読み取り許可が削除され、その他の利用者設定と監査ログが保持されていることも確認する。

Copilot CLI の `/sandbox` で各タブを確認し、初期状態を記録する。無効な場合は、組織による強制がなければ、次の確認の間だけ `/sandbox enable` を実行する。

新しい Copilot CLI セッションの sandbox 内で次を実行し、表示された interpreter が `uv python dir` の保存先またはその実体に属することを確認する。

```powershell
uv run --no-project --managed-python python -c "import sys; print(sys.version); print(sys.executable)"
```

組織による強制がない場合は `/sandbox disable` 後に CLI を終了し、上記の `chezmoi apply` を再実行する。CLI を再起動して無効状態が維持されたことを確認し、初期状態に戻す。

## 結果を記録する

環境ごとに次の表をコピーして記入する。

| 項目 | 結果 |
|---|---|
| 検証日 | |
| 環境 | Linux / WSL2 / macOS / Windows / Codespaces / Dev Container |
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
| bubblewrap version | macOS / Windows は N/A |
| user namespace probe | 終了コード。macOS / Windows は N/A |
| warning またはエラー | |

失敗時は、実行コマンド、終了コード、標準エラー、`/sandbox` の各画面の表示を残す。認証情報や機密性のある環境変数の値は記録へ含めない。記入した表は実施したセッションに残し、リポジトリへは追加しない。
