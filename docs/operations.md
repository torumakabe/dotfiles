# Operations Guide

`README.md` には日常的に使う操作だけを残し、このファイルには **このリポジトリ固有の運用** をまとめる。一般的な `chezmoi` / `mise` の使い方は各公式ドキュメントを参照。

## ツールの管理境界

| 環境 | 管理ツール | 主な対象 |
|------|-----------|----------|
| Linux / WSL | `apt` + `mise` | OS パッケージ、Azure CLI、開発ツール |
| macOS | `brew` + `mise` | OS パッケージ、GUI アプリ、Azure CLI、開発ツール |
| Codespaces / Dev Container | ベースイメージ / Feature + `mise` | コンテナ基盤側ツール、開発ツール |
| Windows | `winget` (DSC) + `mise` | GUI/CLI アプリ、Azure CLI、開発ツール |
| 全環境共通 | `rustup` | Rust toolchain |
| 全環境共通 | `uv` | Python スクリプト実行 |

## 定期チェック対象の制約

`mise` 設定や導入元を見直すときに、次の制約が残っているか確認する。解消されていれば条件分岐やワークアラウンドを外せる。

- **cargo-make**: linux/arm64 向け配布なし
- **npm:typescript-language-server**: 社内 npm プロキシが 5.3.0 の `_npmUser.trustedPublisher` を落とすため `trust_policy_excludes` で 5.3.0 を除外（[docs/troubleshooting.md](troubleshooting.md#mise-install-が-aube-install-failed-failed-to-resolve-dependencies-で止まる)）
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
4. `minimum_release_age` の正規形警告と、`mise-versions ... fallback=true` の回復済み警告以外の `mise WARN` が出力された場合は、既存 lockfile を復元して停止
5. 既存 lockfile を削除し、`mise lock --global --platform ...` で再生成
6. `mise lock` が失敗した場合、または許可対象以外の `mise WARN` が出力された場合は、既存 lockfile を復元して停止
7. `chezmoi re-add`
8. git commit + push

```bash
mise-upgrade
```

### 対象プラットフォームの定義元

対象プラットフォームは `~/.config/mise/config.toml` の `[settings] lockfile_platforms` が正本である。この設定は、auto-lock（`mise install` が実インストール後に走らせる書き戻し）と `--platform` を省略した `mise lock` が使う基準集合を決める。

```toml
[settings]
lockfile_platforms = ["linux-x64", "linux-arm64", "macos-arm64", "windows-x64", "windows-arm64"]
```

この設定には、運用上で把握しておくべき性質が四つある。

- **厳密な許可リストではない。実行中のプラットフォームは設定値に無くても必ず加わる。** 上記に無い環境（musl 系の `linux-x64-musl` など）で `mise install` を実行すると、その環境の分だけエントリが増える。この dotfiles は macOS を Apple Silicon に限定しているため、`macos-x64` は集合に含めていない。
- **明示した `--platform` が設定より優先される。** 別の集合を書きたいときは CLI で指定する。
- **既存エントリは削除されない。** 設定を絞っても、すでに lockfile にあるプラットフォームはそのまま残る。不要なエントリを消すには lockfile を削除して再生成する。
- **グローバル設定なので、他のリポジトリでの lockfile 操作にも及ぶ。** auto-lock が影響を受けるのは、そのリポジトリ自身が `lockfile = true` を有効にしている場合に限る（`lockfile = true` はグローバルからリポジトリへ波及しない）。一方、そのリポジトリで `mise lock` を明示実行した場合は、`lockfile = true` の有無に関わらずこの基準集合が使われる。

### 手動操作の重要ルール

- `mise lock` は **`--global` が必須**（省略するとプロジェクト設定のみ対象になる）
- lockfile 再生成時は **`--platform` を常に指定**する。`lockfile_platforms` があっても省略しない。lockfile を削除してから再生成する破壊的操作であり、設定が読まれない状況（古い mise、設定ファイルの欠落）でも意図した集合になることを保証するため
- `mise upgrade` 後は lockfile を一度削除してから再生成する（既存エントリが残り新版が反映されないため）
- 両シェルとも、`minimum_release_age` の正規形に一致するリリース保留警告と、`mise-versions` が `fallback=true` を明示した回復済み警告だけを許可し、警告内容と継続理由を表示する
- `mise-versions ... fallback=true` は、GitHub Releases などの取得失敗後に代替経路で処理を継続できたことを示す。一時的な `502 Bad Gateway` でも発生するため、この警告だけから `GITHUB_TOKEN` の期限切れとは判断しない
- 両シェルとも、許可対象以外の `mise WARN` が出力された場合は、終了コードが `0` でも lockfile を復元し、commit と push を行わない。`fallback=false`、`fallback` 欠落、形式不明の警告は停止対象とする
- 両シェルとも、`mise upgrade` または `mise lock` の失敗時は、更新処理を始める前の lockfile を復元する
- 処理を停止した関数は、原因となった警告、lockfile の復元結果、実行ログの保存先を標準エラー出力へ表示する。運用者は表示されたログを確認して原因を特定する
- PowerShell では `$env:GITHUB_TOKEN = (gh auth token); <cmd>; $env:GITHUB_TOKEN = $null` でトークンを渡し、`--platform` の値はクォートする

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

## Rust toolchain の更新

Rust toolchain は mise ではなく、全 OS で公式 rustup が管理する（[ADR-016](adr/016-rust-external-rustup.md)）。`mise-upgrade` と `Invoke-MiseUpgrade` は Rust toolchain を更新しない。

default toolchain として stable を使う環境では、次のコマンドで stable を更新する。

```bash
rustup show
rustup update stable
rustc --version
cargo --version
```

`rustup show` で default toolchain が stable 以外を指しており、stable へ戻す場合は、更新後に次のコマンドを実行する。

```bash
rustup default stable
```

プロジェクトに `rust-toolchain.toml` がある場合、rustup はそのファイルの `channel` を default toolchain より優先する。固定バージョンを更新する場合は、対象プロジェクトで `rust-toolchain.toml` を変更し、そのプロジェクトの検証手順を実行する。dotfiles の更新操作では、プロジェクトが指定するバージョンを変更しない。

Linux または WSL で更新後も古い Rust が選択される場合は、次のコマンドで実行ファイルと有効な toolchain を確認する。

```bash
command -v rustup
command -v rustc
rustup show active-toolchain
```

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

## このリポジトリを Dev Container で開発する

`.devcontainer/devcontainer.json` は、このリポジトリ自体を開発するための構成である。dotfiles を任意のプロジェクトの Dev Container へ適用する手順（`README.md` の「Dev Container (ローカル)」節）とは別のものを指す。

dotfiles は `devcontainer.json` からは適用しない。VS Code の Dotfiles ユーザ設定（Repository に `torumakabe/dotfiles`、Install Command に `install.sh`）で入れる。Codespaces がアカウント設定から dotfiles を入れる構造と揃えるためである。**この設定をしていないコンテナには `uv`、`mise`、`chezmoi`、`gitleaks` が入らず、テストを実行できない。**

コンテナ起動後に次を実行する。

```bash
gh auth login
GITHUB_TOKEN=$(gh auth token) mise install --yes
```

構成上の判断は次のとおりである。

- **`image`**：`mcr.microsoft.com/devcontainers/base:ubuntu` を使い、`git` feature は指定し直さない。指定すると `/usr/local` へ git を作り直すことになり、ADR-020 が対象とする「ベースイメージのソースビルドが apt 版を隠す」状態を再現できなくなる
- **`git-lfs` feature**：ベースイメージに `git-lfs` が含まれないため足す。ADR-020 の張り替えが `git-lfs` を対象から外すことを実機で確認するには、`/usr/local/bin/git-lfs` が存在する必要がある
- **`powershell` feature**：dotfiles は Linux に pwsh を入れないため、これが無いと `tests/test_platform_parity.py` と `tests/test_mise_config.py` の PowerShell 依存テストが skip される。CI（ubuntu-latest）は同梱の pwsh を使うので、同じ範囲を流すために足す

chezmoi のコンテナ判定は、環境変数 `CODESPACES` と `REMOTE_CONTAINERS` の有無だけで決まる。`REMOTE_CONTAINERS` を立てるのは VS Code の Dev Containers 拡張であり、`@devcontainers/cli` は立てない。この判定が対象とするのは拡張と Codespaces で起動したコンテナであり、CLI で起動したコンテナは対象外である。CLI を対象へ含めるには `/.dockerenv` のような別の指標を足すことになるが、判定の軸が増えるため採らない。

CLI で検証するときは `--remote-env REMOTE_CONTAINERS=true` を渡す。渡さないと `.devcontainer` が false になり、Docker Engine、draw.io、Azure CLI など、ホストへ入れる前提の導入処理がコンテナ内で走る。Docker Desktop の WSL2 バックエンドではコンテナがホストの WSL カーネルを共有して `.isWSL` が true になるため Docker Engine と draw.io は止まるが、macOS や Linux の Docker で起動したコンテナでは止まらない。

Windows ホストでは、`tests/test_git_shadow_resolution.py` のうち POSIX 版のチェックスクリプトを実行するテストが skip される。`bash` が WSL の interop 版に解決され、テストが用意した偽の git を参照できないためである。全件を実行するには、このコンテナか WSL、または CI を使う。

## プラットフォーム契約の運用確認

開発者は公開関数、alias、補完、ツール導入を変更した後、契約とmise設定の回帰検査を実行する。

```bash
uv run -m unittest tests.test_platform_parity tests.test_mise_config -v
```

CIはzshとpwshの存在を確認した後、全テストをdiscover形式で実行する。

## git pre-commit フック

`~/.config/git/templates/hooks/pre-commit` を `gitleaks` の scan スクリプトとして配置し、`init.templateDir` 経由で新規リポジトリ（`git init`/`git clone`）にのみ既定配布する（ADR-018）。

```bash
git config --global init.templateDir   # 期待値: ~/.config/git/templates
chezmoi edit ~/.config/git/templates/hooks/pre-commit && chezmoi apply
```

既存リポジトリへの backfill（`git init` の再実行は既存 hook を上書きしないため安全・冪等）:

```bash
git -C <repo-path> init
```

状態の確認は `git-hooks-audit`（zsh）/ `Invoke-GitHooksAudit`（PowerShell）で ghq 管理下の全リポジトリを一括チェックできる。

Git 2.54 以降では、設定ベースフック（ADR-020）が全リポジトリで加算的に走る。

```bash
git hook list --show-scope pre-commit   # 期待値: global<TAB>dotfiles-gitleaks
chezmoi edit ~/.local/bin/gitleaks-pre-commit && chezmoi apply
git config --local hook.dotfiles-gitleaks.enabled false   # リポジトリ単位で無効化
```

`git hook list` が `unknown subcommand` で失敗する場合、その git は 2.54 より前であり `init.templateDir` だけが効いている。

設定ベースフックが有効かどうかは `chezmoi apply` のたびに確認され、無効なら原因ごとに案内を変えた警告が出る。復旧手順は [`troubleshooting.md`](troubleshooting.md#設定ベースフックが全リポジトリで動いていない) を参照。

## `run_once_*` の再実行

```bash
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

実行順は [`architecture.md`](architecture.md#run_once_-スクリプトの実行順) を参照。
