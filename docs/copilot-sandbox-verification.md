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

## 実 CLI で hook interpreter と uv の既定 cache grant を確認する

Copilot CLI 1.0.92-4 以降では、CLI 起動環境から `UV_CACHE_DIR` を除いた状態で、uv の既定 cache が sandbox の `filesystem.readwritePaths` に追加されることを確認する。候補実装の実機検証では、Copilot 設定と hook を一時ディレクトリへ複製し、実ユーザーの設定ファイルを変更しない。

実機検証の対象は macOS、Windows native、WSL2 とする。Windows native は GitHub Copilot App の Windows セッション、WSL2 は WSL 内で起動した Copilot CLI を使う。検証手順は各セッションへ直接貼り付け、計画書や一回限りの probe はリポジトリへ追加しない。

各環境で、次を確認する。

- `chezmoi apply` が `python-runtime.env` を生成し、記録した interpreter で launcher のスモークテストが成功する
- 全5件の hook が launcher から起動し、hook プロセス内で mise と uv を起動しない
- 記録した interpreter が uv managed Python root 配下にあり、標準ライブラリの `encodings` を読み込める
- 通常の shell tool 内では mise 管理コマンドを従来どおり実行できる
- uv が自動探索した Python で `--offline --no-project --no-env-file --no-python-downloads` を指定した実行が成功する
- 通常の shell から取得した uv の既定 cache に marker を書き込める
- 生成 policy が同じ既定 cache を `readwritePaths` に含む
- 生成 policy が `~/.copilot/hooks`、通常の shell tool に必要な mise path、runtime env の `python_root` を `readonlyPaths` に含む
- 旧専用 `github-copilot/uv` を生成 policy に追加しない
- `python` と `pip` の直接実行拒否、および `uv run` と `uv pip` の無変更通過を維持する

外部モデル、対話ログイン、ネットワークアクセス、Python の新規ダウンロードは使用しない。marker と一時ファイルは検証終了時に削除する。

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

## 検証結果の記録

macOS の候補実装検証は成功済みである。Windows native と WSL2 は同じ候補実装の commit SHA を使って実機検証し、結果をこのセッションへ返す。Linux native は今回の実機検証対象外であり、テンプレート生成と静的テストの確認範囲に限る。
