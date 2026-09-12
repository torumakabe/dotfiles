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

実ユーザーの設定を変更せず、レンダリング済みスクリプトによる `sandbox.enabled` の保持を検査する。

```bash
uv run -m unittest \
  tests.test_copilot_sandbox_config.CopilotSandboxEnabledPreservationTests -v
```

## 実 CLI でキャッシュの永続化を比較する

通常の HOME とツール構成を使い、インストール済みの CLI で比較する。Copilot 設定は一時ディレクトリへ複製し、実ユーザーの設定ファイルは変更しない。専用キャッシュには実際に書き込み、検証用の一意なファイルだけを終了時に削除する。

```bash
COPILOT_UV_PROBE_PATH="$PATH" COPILOT_UV_PROBE_VIRTUAL_ENV="${VIRTUAL_ENV-}" \
  COPILOT_CLI_INTEGRATION=1 PYTHONDONTWRITEBYTECODE=1 \
  uv run -m unittest tests.test_copilot_sandbox_cli -v
```

localhost の固定応答 provider が uv コマンドを選び、実 CLI が sandbox を構築する。外部モデルとログインは不要である。毎回新しい CLI プロセスと隔離設定を使い、`allowDevToolAccess=true`、`allowBypass=false` を維持する。`--allow-all-tools` / `--allow-all-paths` は承認省略のためであり、OS sandbox は無効にしない。

一時リポジトリに配布対象の preToolUse hook 一式を登録し、実際にコマンドの変更が返されたことも確認する。テスト起動前の PATH と仮想環境指定を CLI へ渡し、テストランナーの `uv run` が選んだ Python を自動許可の根拠にしない。検査対象の Python を `--python` で指定せず、テスト専用の Python RO も追加しない。既存の RO / deny を維持し、専用キャッシュに対する RW の有無を比較する。

許可なしでは、一意な検証ファイルがホストへ作成されないことを確認する。許可ありでは、uv の成功、ホスト側の `CACHEDIR.TAG`、検証ファイルの内容一致を要求する。既存キャッシュの有無やプロセスの終了コードだけを成功条件にしない。この試験は Python の新規ダウンロードを許可しない。

## dotfiles を適用する

差分を確認してから適用する。

```bash
repo_root="$(git rev-parse --show-toplevel)"
chezmoi --source "${repo_root}/home" diff
chezmoi --source "${repo_root}/home" apply
```

Linux 系では `sandbox.enabled` が `true` または未設定の場合に bubblewrap 診断が実行される。`false` の場合は probe を省略する。warning が出た場合は、後述の確認結果とともに記録する。

## Copilot CLI の対話動作を確認する

uv の書き込み許可は、通常の `uv cache dir` と sandbox 内の出力を比較し、`uv run` 後にホスト側へファイルが残ることまで確認する。`/sandbox policy` の表示だけでは成功と扱わない。プロジェクト固有のキャッシュ設定がある場合は、ユーザー共通設定との差も記録する。

`tests.test_copilot_sandbox_config` の backend テストは、単純な OS 書き込み制限下で、許可なしの uv が失敗し、生成した実体パスへの許可ありで成功することを確認する。Copilot CLI が組み立てた実効ポリシーの試験ではないため、CLI と WSL の実機確認を代替しない。

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

## uv キャッシュ許可の実 CLI 検証（2026-09-11）

現在の実装は POSIX のコマンド内で専用キャッシュを選び、通常シェルの uv 設定は変更しない。commit `34b6fba` の配布対象 hook、通常 HOME と PATH、Python 自動探索を使い、検証専用の Python RO を追加せず比較した。

macOS では、RW なしの場合に専用キャッシュの初期化が `Operation not permitted` で失敗し、uv は終了コード2、検証ファイルは残らなかった。RW ありでは管理下の Python 3.14を自動選択し、uv は終了コード0となり、`CACHEDIR.TAG` と検証ファイルがホストへ残った。通常設定へ適用後、新しい Copilot CLI プロセスを localhost の固定応答 provider で起動し、hookが `~/Library/Caches/github-copilot/uv` を選択することと、検証ファイルのホスト永続化を確認した。適用前のファイルは `~/.cache/copilot-uv-deploy.5hv61N` へ保存した。

WSL2 では、RW なしでも uv は終了コード0となったが、検証ファイルはホストへ残らなかった。RW ありでは `/usr/bin/python3` を自動選択し、uv は終了コード0となり、`CACHEDIR.TAG` と検証ファイルがホストへ残った。commit `34b6fba` を通常設定へ適用した後、再起動した Copilot CLI で hook が `~/.cache/github-copilot/uv` を選択し、通常の WSL 端末から検証ファイルを読み取れることを確認した。適用前のファイルは `~/.cache/copilot-uv-deploy.sOzKbf/backup` へ保存した。
