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
| 全環境共通 | `gh extension` + `gh skill` | `gh-stack` extension と Copilot skill |

## 定期チェック対象の制約

`mise` 設定や導入元を見直すときに、次の制約が残っているか確認する。解消されていれば条件分岐やワークアラウンドを外せる。

- **cargo-make**: linux/arm64 向け配布なし
- **npm:typescript-language-server**: 利用中の npm レジストリプロキシが trusted publisher の証跡を保持しない版だけを `trust_policy_excludes` の対象とする。対象版は `home/dot_config/mise/config.toml.tmpl` を正本とする
- **azure-dev**: mise `github:` バックエンドがバイナリ名を正規化しないため mise 外管理（macOS: `brew` / Windows: `winget` / Linux: `install-azd.sh`、更新は `azd update`）
- **copilot-cli**: mise の `github:` バックエンドで更新遅延・バージョン誤認が起きるため mise 外管理（macOS: `brew` / Windows: `winget` / Linux: `gh.io/copilot-install`、更新は `copilot update`）
- **edit**（Microsoft Edit）: Windows のみ winget/DSC で管理（`reference/windows/configuration.dsc.yaml`）。macOS / Linux では未使用

TypeScript language server の除外を撤去するときは、`home/dot_config/mise/config.toml.tmpl` の版限定エントリを削除し、`mise install --force npm:typescript-language-server` で既存導入済み版も再検証する。成功後に `uv run -m unittest tests.test_mise_config -v` を実行する。失敗時の確認は [`troubleshooting.md`](troubleshooting.md#mise-install-が-aube-install-failed-failed-to-resolve-dependencies-で止まる) を参照する。

## gh-stack の更新

セットアップスクリプトは、`gh-stack` の GitHub CLI extension と公式 Copilot skill が未導入の場合だけ、その時点の最新安定版を取得する。`chezmoi apply` は導入済みの版を更新しないため、端末の構築時期によって版が異なり得る。

更新前には、skill と extension の候補を確認する。

```bash
gh skill update gh-stack --dry-run
gh extension upgrade gh-stack --dry-run
```

更新する場合は、公式 skill の内容と extension のリリースノートを確認してから、`gh skill update gh-stack` と `gh extension upgrade gh-stack` を明示的に実行する。更新後は `gh skill list --agent github-copilot --scope user`、`gh extension list`、`gh stack --version` で導入版を確認する。日常の apply へ更新処理を含めない理由は [ADR-024](adr/024-gh-stack-distribution-and-updates.md) を参照する。

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

dotfiles は `devcontainer.json` から適用しない。VS Code の Dotfiles ユーザ設定は `README.md` の「Dev Container (ローカル)」節に従う。この設定がないコンテナにはテストに必要なツールが入らない。

CLI で起動または更新するときは、chezmoi の Dev Container 判定に必要な環境変数を渡す。

```bash
devcontainer up --workspace-folder . --remote-env REMOTE_CONTAINERS=true
```

コンテナ起動後に次を実行する。

```bash
gh auth login
GITHUB_TOKEN=$(gh auth token) mise install --yes
chezmoi apply
```

最後の `chezmoi apply` は、コンテナ作成時に `gh` の認証やツール導入を待って終了した `run_after` 処理を再実行する。

イメージ内の Git を維持する理由は [ADR-020](adr/020-git-hooks-via-config.md)、PowerShell を含むクロスプラットフォーム検査の保証範囲は [ADR-019](adr/019-cross-platform-parity-contract.md) を参照する。

Windows ホストでは、`tests/test_git_shadow_resolution.py` のうち POSIX 版のチェックスクリプトを実行するテストが skip される。`bash` が WSL の interop 版に解決され、テストが用意した偽の git を参照できないためである。全件を実行するには、このコンテナか WSL、または CI を使う。

構成を更新した後は、コンテナ内で全テストを実行する。

```bash
PYTHONDONTWRITEBYTECODE=1 uv run -m unittest discover -s tests
```

## プラットフォーム契約の運用確認

開発者は公開関数、alias、補完、ツール導入を変更した後、契約とmise設定の回帰検査を実行する。

```bash
uv run -m unittest tests.test_platform_parity tests.test_mise_config -v
```

CIはzshとpwshの存在を確認した後、全テストをdiscover形式で実行する。

## git pre-commit フック

テンプレートフックと設定ベースフックを更新するときは、対応する二つの起動スクリプトを同じ変更で編集する。配布方式と保証範囲は [ADR-018](adr/018-git-hooks-via-init-templatedir.md) と [ADR-020](adr/020-git-hooks-via-config.md) を参照する。

```bash
chezmoi edit ~/.config/git/templates/hooks/pre-commit
chezmoi edit ~/.local/bin/gitleaks-pre-commit && chezmoi apply
git-hooks-audit
git hook list --show-scope pre-commit
```

PowerShell では `git-hooks-audit` の代わりに `Invoke-GitHooksAudit` を使う。確認結果が想定と異なる場合は、[`troubleshooting.md`](troubleshooting.md#新規リポジトリに-gitleaks-pre-commit-hook-が入らない) と [`troubleshooting.md`](troubleshooting.md#設定ベースフックが全リポジトリで動いていない) を参照する。

設定ベースフックを現在のリポジトリだけで無効化するには、次を実行する。再有効化は `git config --local --unset hook.dotfiles-gitleaks.enabled` で行う。

```bash
git config --local hook.dotfiles-gitleaks.enabled false
```

## `run_once_*` の再実行

```bash
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

実行順は [`architecture.md`](architecture.md#セットアップスクリプトの実行順) を参照。
