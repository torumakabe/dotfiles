# Operations Guide

`README.md` には日常的に使う操作だけを残し、このファイルには **このリポジトリ固有の運用** をまとめる。一般的な `chezmoi` / `mise` の使い方は各公式ドキュメントを参照。

## ツールの管理境界

| 環境 | 管理ツール | 主な対象 |
|------|-----------|----------|
| Linux / WSL | `apt` + `mise` | OS パッケージ、Azure CLI、開発ツール |
| macOS | `brew` + `mise` | OS パッケージ、GUI アプリ、Azure CLI、開発ツール |
| Codespaces / Dev Container | ベースイメージ / Feature + `mise` | コンテナ基盤側ツール、開発ツール |
| Windows | `winget` (DSC) + `mise` | GUI/CLI アプリ、Azure CLI、開発ツール |
| 全環境共通 | `uv` | Python スクリプト実行 |

## 定期チェック対象の制約

`mise` 設定や導入元を見直すときに、次の制約が残っているか確認する。解消されていれば条件分岐やワークアラウンドを外せる。

- **cargo-make**: linux/arm64 向け配布なし
- **azure-dev**: mise `github:` バックエンドがバイナリ名を正規化しないため mise 外管理（macOS: `brew` / Windows: `winget` / Linux: `install-azd.sh`、更新は `azd update`）
- **copilot-cli**: mise の `github:` バックエンドで更新遅延・バージョン誤認が起きるため mise 外管理（macOS: `brew` / Windows: `winget` / Linux: `gh.io/copilot-install`、更新は `copilot update`）
- **edit**（Microsoft Edit）: Windows のみ winget/DSC で管理（`reference/windows/configuration.dsc.yaml`）。macOS / Linux では未使用

## chezmoi での編集

通常は `chezmoi edit`。テンプレート全体を見ながら編集したいときだけソースを直接触る。

```bash
chezmoi edit ~/.zshrc   # または: vim "$(chezmoi source-path)/../home/dot_zshrc.tmpl"
chezmoi diff && chezmoi apply
```

## mise の保守

### `mise-self-upgrade`

Windows で mise 本体を winget 管理として更新する。

```powershell
mise-self-upgrade
```

このコマンドは `winget upgrade --id jdx.mise --source winget --disable-interactivity --force` を実行し、更新があった場合は続けて `mise reshim` を実行する。更新がない場合は正常終了する。winget portable package の symlink 判定により通常の upgrade が「変更済み」と誤検知されることがあるため、mise 本体の更新ではこの関数を使う。

Copilot CLI など mise shim 経由のプロセスが動いていると winget が `mise.exe` を削除できないため、実行前に検出して停止を促す。

### `mise-upgrade`

zsh の `mise-upgrade` と PowerShell の `Invoke-MiseUpgrade` は、処理を始める前に既存 lockfile を退避してから次を一括実行する。

1. `gh auth token` で一時トークンを取得
2. 既存 lockfile を退避
3. `mise upgrade`
4. `minimum_release_age` の正規形警告以外の `mise WARN` が出力された場合は、既存 lockfile を復元して停止
5. 既存 lockfile を削除し、`mise lock --global --platform ...` で再生成
6. `mise lock` が失敗した場合、または正規形以外の `mise WARN` が出力された場合は、既存 lockfile を復元して停止
7. `chezmoi re-add`
8. git commit + push

```bash
mise-upgrade
```

### 手動操作の重要ルール

- `mise lock` は **`--global` が必須**（省略するとプロジェクト設定のみ対象になる）
- lockfile 再生成時は **`--platform` を常に指定**
- `mise upgrade` 後は lockfile を一度削除してから再生成する（既存エントリが残り新版が反映されないため）
- 両シェルとも、`minimum_release_age` の正規形に一致するリリース保留警告だけを許可し、警告内容を表示して処理を継続する
- 両シェルとも、正規形以外の `mise WARN` が出力された場合は、終了コードが `0` でも lockfile を復元し、commit と push を行わない
- 両シェルとも、`mise upgrade` または `mise lock` の失敗時は、更新処理を始める前の lockfile を復元する
- 処理を停止した関数は、原因となった警告、lockfile の復元結果、実行ログの保存先を標準エラー出力へ表示する。運用者は表示されたログを確認して原因を特定する
- PowerShell では `$env:GITHUB_TOKEN = (gh auth token); <cmd>; $env:GITHUB_TOKEN = $null` でトークンを渡し、`--platform` の値はクォートする

対象プラットフォーム: `linux-x64`, `linux-arm64`, `macos-arm64`, `windows-x64`, `windows-arm64`

### 典型コマンド

```bash
# mise upgrade + lockfile 再生成
GITHUB_TOKEN=$(gh auth token) mise upgrade
rm -f ~/.config/mise/mise.lock
GITHUB_TOKEN=$(gh auth token) mise lock --global --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
chezmoi re-add ~/.config/mise/mise.lock

# ツール追加・削除
chezmoi edit ~/.config/mise/config.toml
GITHUB_TOKEN=$(gh auth token) mise install
GITHUB_TOKEN=$(gh auth token) mise lock --global --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
chezmoi re-add ~/.config/mise/config.toml ~/.config/mise/mise.lock
```

lockfile を削除して再生成したいケース: 新プラットフォーム追加、不要プラットフォーム除去、lockfile 破損。

## GitHub API と `GITHUB_TOKEN`

`mise` は GitHub API を使うため、未認証だとレート制限に当たりやすい。

```bash
gh auth login
GITHUB_TOKEN=$(gh auth token) mise install
```

`GITHUB_TOKEN` を `.zshrc` や `$PROFILE` に常駐させないこと。

## Bootstrap / shell pin の更新

初期セットアップ系スクリプトは、上流の最新版をその場で実行せず、リリース番号や SHA256 を pin している。更新時は **バージョン更新 → 公式チェックサム確認 → スクリプト反映** の順で行う。

- `install.sh`: `CHEZMOI_VERSION` と対応する SHA256
- `home/run_once_before_20-install-mise.sh.tmpl`: `MISE_VERSION` と対応する SHA256
- `home/run_once_after_10-setup-shell.sh.tmpl`: `OH_MY_ZSH_COMMIT`, `ZSH_COMPLETIONS_TAG`

最低限の確認:

```bash
shellcheck install.sh
sed '/^{{/d' home/run_once_before_20-install-mise.sh.tmpl | bash -n
sed '/^{{/d' home/run_once_after_10-setup-shell.sh.tmpl | bash -n
```

## プラットフォーム契約の運用確認

開発者は公開関数、alias、補完、ツール導入を変更した後、契約とmise設定の回帰検査を実行する。

```bash
uv run -m unittest tests.test_platform_parity tests.test_mise_config -v
```

CIはzshとpwshの存在を確認した後、全テストをdiscover形式で実行する。

## git pre-commit フック

`~/.config/git/templates/hooks/pre-commit` を `gitleaks` の scan スクリプトとして配置し、`init.templateDir` 経由で新規リポジトリ（`git init`/`git clone`）にのみ既定配布する（ADR-018、旧 `core.hooksPath` グローバル方式からの移行）。

```bash
git config --global init.templateDir   # 期待値: ~/.config/git/templates
chezmoi edit ~/.config/git/templates/hooks/pre-commit && chezmoi apply
```

既存リポジトリへの backfill（`git init` の再実行は既存 hook を上書きしないため安全・冪等）:

```bash
git -C <repo-path> init
```

状態の確認は `git-hooks-audit`（zsh）/ `Invoke-GitHooksAudit`（PowerShell）で ghq 管理下の全リポジトリを一括チェックできる。

## `run_once_*` の再実行

```bash
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

実行順は [`architecture.md`](architecture.md#run_once_-スクリプトの実行順) を参照。
