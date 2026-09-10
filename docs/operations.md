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
- **azure-dev**: mise `github:` バックエンドがバイナリ名を正規化しないため mise 外管理（macOS: `brew` / Windows: `winget` / Linux: 固定した公式 `.deb`、更新は `azd update`）
- **copilot-cli**: mise の `github:` バックエンドで更新遅延やバージョン誤認が起きるため mise 外管理（macOS: `brew` / Windows: `winget` / Linux: 固定した公式リリースアーカイブ、更新は `copilot update`）
- **edit**（Microsoft Edit）: Windows のみ winget/DSC で管理（`reference/windows/configuration.dsc.yaml`）。macOS / Linux では未使用

TypeScript language server の除外を撤去するときは、`home/dot_config/mise/config.toml.tmpl` の版限定エントリを削除し、`mise install --force npm:typescript-language-server` で既存導入済み版も再検証する。成功後に `uv run -m unittest tests.test_mise_config -v` を実行する。失敗時の確認は [`troubleshooting.md`](troubleshooting.md#mise-install-が-aube-install-failed-failed-to-resolve-dependencies-で止まる) を参照する。

## gh-stack の更新

セットアップスクリプトは、`gh-stack` の GitHub CLI extension と公式 Copilot skill が未導入の場合だけ、その時点の最新安定版を取得する。skill の一覧取得と更新用メタデータの記録に対応するため、初期セットアップには GitHub CLI 2.94 以降が必要である。`chezmoi apply` は導入済みの版を更新しないため、端末の構築時期によって版が異なり得る。

更新前には、skill と extension の候補を確認する。

```bash
gh skill update gh-stack --dry-run
gh extension upgrade gh-stack --dry-run
```

更新する場合は、公式 skill の内容と extension のリリースノートを確認してから、`gh skill update gh-stack` と `gh extension upgrade gh-stack` を明示的に実行する。更新後は `gh skill list --agent github-copilot --scope user`、`gh extension list`、`gh stack --version` で導入版を確認する。日常の apply へ更新処理を含めない理由は [ADR-024](adr/024-gh-stack-distribution-and-updates.md) を参照する。

## Copilot local sandbox の既定値

`chezmoi apply` は `~/.copilot/settings.json` の user-level 設定へ sandbox policy をマージする。`sandbox.enabled` が未設定の場合、通常の macOS、Windows、Linux、WSL では `true`、Codespaces と Dev Container では `false` を設定する。既存値が boolean であれば、他のリポジトリ管理キーをマージした後にその値を復元する。既存値が null や真偽値以外の場合は、`chezmoi apply` を明示的なエラーで止める。

同期処理は、トップレベルと `sandbox` 配下のどちらでも、リポジトリが管理しないキーを保持する。filesystem の `readwritePaths`、`readonlyPaths`、`deniedPaths` は、未設定または null の場合だけ空配列へ正規化し、既存の配列を保持する。文字列、数値、真偽値、オブジェクトなどの非配列値は、設定ファイルを書き換える前にエラーとして拒否する。

現行ポリシーと競合する旧設定は例外として削除する。対象は `sandbox.userPolicy.network.allowedHosts`、`sandbox.userPolicy.network.blockedHosts`、旧 Windows AppContainer schema の `sandbox.userPolicy.version` である。同期処理は JSON 全体を再シリアライズするため、保持するキーでもインデントとキー順は変わる場合がある。

利用者は `/sandbox enable` と `/sandbox disable` で値を変更でき、変更後の boolean 値も次回の適用で維持される。コンテナでの手動有効化は互換性調査の対象であり、このリポジトリは動作を保証しない。Copilot CLI が sandbox 外での再実行方法を常に提示するとは限らない。WinGet Configuration は Copilot CLI パッケージの導入だけを担い、設定ファイルは配布しない。環境別の初期値を採用した判断は [ADR-026](adr/026-copilot-cli-sandbox-environment-defaults-and-explicit-setting-preservation.md) を参照する。

組織が enterprise の managed-settings.json（Linux 系 `/etc/github-copilot/managed-settings.json`、macOS `/Library/Application Support/GitHubCopilot/managed-settings.json`、Windows `%ProgramFiles%\GitHubCopilot\managed-settings.json`）で sandbox を強制している場合、`/sandbox` の UI は managed もしくは locked と表示され、利用者はローカルで無効化できない。これは組織のポリシーによるものであり、本リポジトリの chezmoi 設定は関与しない。

本リポジトリの以前のブランチ（file-based managed settings 方式）が残した設定の確認と復旧は、[`troubleshooting.md`](troubleshooting.md#copilot-sandboxenabled-が意図した値にならない) を参照する。

更新後は Copilot CLI を再起動し、`/sandbox` の General、Auth、Filesystem、Network の各タブを確認する。Linux 系では `sandbox.enabled` が `true` または未設定の場合だけ bubblewrap 診断が実行され、`false` の場合は probe が省略される。

WSL2、macOS、Codespaces、Dev Container でリモートブランチを検証するときは、[Copilot CLI local sandbox 実機検証](copilot-sandbox-verification.md) に従う。ホストからの非対話起動だけでスラッシュコマンドや backend を確認済みと扱わない。

## chezmoi での編集

通常は `chezmoi edit`。テンプレート全体を見ながら編集したいときだけソースを直接触る。

```bash
chezmoi edit ~/.zshrc   # または: vim "$(chezmoi source-path)/../home/dot_zshrc.tmpl"
chezmoi diff && chezmoi apply
```

## mise の保守

### 本体の導入元

macOS と Linux は、`home/run_once_before_20-install-mise.sh.tmpl` が固定版の公式 GitHub Releases アーカイブを取得し、SHA-256 検証後に `~/.local/bin/mise` へ配置する。Windows は DSC の `jdx.mise` を使い、winget が公式 GitHub Releases ZIP を配置する。導入経路は OS ごとに異なるが、全 OS で mise の公式成果物を使う（[ADR-027](adr/027-mise-install-from-official-artifacts-per-os.md)）。

macOS に Homebrew formula の mise がある場合、現在解決される mise が formula の実体であるか、mise が未解決のときだけ、導入スクリプトは検証済みの公式バイナリを原子的に配置する。現在 `command -v mise` で解決される formula 以外の mise、または標準配置先 `~/.local/bin/mise` にある実行可能な mise は置き換えない。PATH 外の任意の場所は探索しない。現在のシェルが Homebrew の絶対パスを含む activation hook を保持している可能性があるため、導入スクリプトは formula を削除しない。Homebrew 版の activation を読み込んだ既存のシェルをすべて終了し、新しいシェルで `command -v mise` が導入スクリプトの案内したパスを返すことを確認してから、`brew uninstall mise` を手動で実行する。

### 実体環境への切替

mise の導入、lock、通常更新は維持する。Unix の共有 profile は公式 `mise env` で実体 PATH と SDK 環境を設定し、対話 zsh でも `mise activate zsh` は実行しない。Copilot の全5 command hook は host 上で `MISE_ENABLE_TOOLS=uv uv run ...` を使う。Windows は既存の PowerShell activation から実体環境を継承する。

切替の受け入れ条件は、Copilot の sandbox 内で宣言済みの mise 管理ツールがすべて shim を経由せず実体から解決することである。uv は command hook が必要とするため確認の起点になるが、条件は uv だけに限らない。設定に宣言していないツールの shim は過去の導入の残骸であり、shim 経由でも版を解決できないため、この条件の対象から除く。

変更対象の profile と `~/.copilot/hooks/hooks.json` を、端末内の専用作業ディレクトリへ属性とリンクを保持して退避する。CLI 実体を更新する場合はその実体も退避する。元の不在と変更前後の内容を記録し、並行変更を復元で上書きしない。

Unix では `.profile`、`.zprofile`、`.zshenv` を一組として反映する。新しい親ターミナルから CLI を起動し、GUI は通常の起動方法で別に確認する。古い環境や login snapshot を持つアプリと CLI を再起動し、同じプロセス内で子シェルだけを作って反映済みとは判断しない。最初の hook で uv の解決先を確認する。通常 agent shell から見つかることは、hook の親 PATH から見つかる証拠にはならない。

受け入れ条件は、各環境の sandbox 内で確認する。対象の名前は `mise bin-paths` が返す実体ディレクトリの実行ファイルから取る。名前の出所を宣言側に置くことで、shim の有無に依存せず、宣言していないツールの残骸も混ざらない。

確認は host と sandbox の2段に分ける。Windows の sandbox 内では mise が global config を読めず `mise bin-paths` が空を返すため、名前の一覧は host 側で作る。まず host のターミナルで一覧を作る。

```sh
mise bin-paths | while read -r dir; do
    for file in "$dir"/*; do
        [ -x "$file" ] && [ ! -d "$file" ] &&
            printf '%s\t%s\n' "$(basename "$file")" "$file"
    done
done | awk -F '\t' '!seen[$1]++' > "$HOME/mise-tool-paths.tsv"
wc -l < "$HOME/mise-tool-paths.tsv"
```

```powershell
$extensions = $env:PATHEXT -split ';'
$seen = @{}
& mise bin-paths | ForEach-Object {
    Get-ChildItem -LiteralPath $_ -File -ErrorAction SilentlyContinue |
        Where-Object { $extensions -contains [IO.Path]::GetExtension($_.Name) } |
        ForEach-Object {
            $extension = [IO.Path]::GetExtension($_.Name)
            $name = $_.Name.Substring(0, $_.Name.Length - $extension.Length)
            if (-not $seen.ContainsKey($name)) { $seen[$name] = $_.FullName }
        }
}
$seen.GetEnumerator() | Sort-Object Name | ForEach-Object {
    "{0}`t{1}" -f $_.Name, $_.Value
} | Set-Content -LiteralPath (Join-Path $env:USERPROFILE 'mise-tool-paths.tsv')
```

次に sandbox 内で解決先を確認する。zsh と bash では次を実行する。

```sh
entries=$(cat "$HOME/mise-tool-paths.tsv")
[ -n "$entries" ] || printf '%s\n' "no entries: the host list is empty"
printf '%s\n' "$entries" | while IFS="$(printf '\t')" read -r name expected; do
    [ -n "$name" ] && [ -n "$expected" ] || continue
    resolved=$(command -v "$name") || { printf '%s\n' "unresolved: $name"; continue; }
    case "$resolved" in
        "$expected") ;;
        */shims/*) printf '%s\n' "via shim: $name -> $resolved (expected $expected)" ;;
        *) printf '%s\n' "outside mise bin paths: $name -> $resolved (expected $expected)" ;;
    esac
done
```

PowerShell では次を実行する。

```powershell
$entries = Get-Content -LiteralPath (Join-Path $env:USERPROFILE 'mise-tool-paths.tsv')
if (-not $entries) { 'no entries: the host list is empty' }
$entries | ForEach-Object {
    $name, $expected = $_ -split "`t", 2
    $resolved = (Get-Command $name -ErrorAction SilentlyContinue).Source
    if (-not $resolved) { "unresolved: $name" }
    elseif ($resolved -like '*\shims\*') {
        "via shim: $name -> $resolved (expected $expected)"
    }
    elseif (-not [IO.Path]::GetFullPath($resolved).Equals(
        [IO.Path]::GetFullPath($expected),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        "outside mise bin paths: $name -> $resolved (expected $expected)"
    }
}
```

出力が空であれば条件を満たす。一覧が空のときは `no entries` を出す。空の一覧は該当なしと区別できず、確認できていない状態だからである。shim だけでなく、system や Homebrew の同名コマンドが mise の実体より先に選ばれた場合も報告する。Windows の sandbox 内では `LOCALAPPDATA` がパッケージ配下へリダイレクトされるため、host 側で記録した実体パスとの比較を使う。出力がある名前は切替の失敗として扱う。確認後は一覧のファイルを削除する。

Linux の CLI 初回導入版は1.0.83である。既存 CLI は初回導入処理では更新されないため、1.0.80以前の場合は導入元の標準更新方法を使う。GUI 同梱 runtime は別に版と login-shell 環境取得の有無を確認する。

失敗時は変更後の対象を保存してから、退避した profile、hook、更新した CLI 実体を復元し、新しい親プロセスから旧コマンドを起動する。新規作成したファイルは、変更後の内容から変わっていない場合だけ除去して元の不在へ戻す。既存ファイルに別の変更があれば上書きせず停止する。

macOS の shim リンクと Windows User PATH の shim 登録は、この変更では撤去しない。後で撤去する場合は、macOS の対象リンク、リンク先、管理state（`${XDG_STATE_HOME:-$HOME/.local/state}/chezmoi-dotfiles/mise-shim-links`）、Windows User PATH の変更部分を追加で退避する。Windows は変更した要素の位置を記録し、他の PATH 要素を巻き戻さずに復元する。並行変更で安全に復元できない場合は停止する。登録を撤去する前に復元手順を確認する。

実体と依存先の解決、更新と復元の結果は、sandbox 内の実作業結果と分けて記録する。新たな失敗は変更との関係を切り分け、未実行の処理を成功と推定しない。

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

初期セットアップ系スクリプトは、上流の最新版をその場で実行しない。ダウンロードする成果物はバージョンと公式 SHA-256、Git から取得するソースは完全な commit SHA で固定する。各値は、その値を定義するスクリプトを正本とする。

| 正本 | pin |
|------|-----|
| `install.sh` | `CHEZMOI_VERSION` とアーキテクチャ別 SHA-256 |
| `home/run_once_before_20-install-mise.sh.tmpl` | `MISE_VERSION` とアーキテクチャ別 SHA-256 |
| `home/run_once_before_10-install-packages.sh.tmpl` | `COPILOT_VERSION`、`AZD_VERSION`、`RUSTUP_VERSION` と各プラットフォーム別 SHA-256、Microsoft 署名鍵の primary-key fingerprint |
| `home/run_once_after_30-install-tools.sh.tmpl` | `DRAWIO_VERSION` とアーキテクチャ別 SHA-256 |
| `home/run_once_after_10-setup-shell.sh.tmpl` | `OH_MY_ZSH_COMMIT`、zsh-completions の更新確認用 `ZSH_COMPLETIONS_TAG` と取得を強制する `ZSH_COMPLETIONS_COMMIT` |

成果物を更新するときは、バージョンに対応する公式 SHA-256 を確認してからスクリプトへ反映する。現在の draw.io 配布フローには公式 checksum がないため、更新担当者が対象リリース asset の SHA-256 を計算し、上流リリースの出所と asset を確認してから pin を更新する。zsh-completions を更新するときは、タグが指す commit を完全な SHA まで解決して確認し、`ZSH_COMPLETIONS_TAG` と `ZSH_COMPLETIONS_COMMIT` を同時に更新する。取得と取得後の検証には `ZSH_COMPLETIONS_COMMIT` だけを使う。

ダウンロード開始前または通信中の失敗は、警告を表示して対象ツールを省略し、後続の chezmoi スクリプトを継続する。ダウンロードが完了した後の checksum または署名鍵 fingerprint の不一致は、取得物を信頼できないため、そのスクリプトを異常終了させる。リポジトリ鍵や apt metadata の取得失敗も警告を表示して、そのリポジトリに依存するツールだけを省略する。

`run_once` とコマンド存在確認は、pin の変更を導入済み端末へ適用する更新機構ではない。pin の変更は新規環境の導入内容を決める。macOS の Homebrew formula から公式バイナリへの移行だけは例外であり、解決される mise が formula の実体である場合、または mise が未解決の場合に移行処理を実行する。導入済み端末では、mise は macOS と Linux で `mise self-update`、Windows で `mise-self-upgrade` を実行する。Copilot CLI は `copilot update`、Azure Developer CLI は `azd update`、rustup 自体は `rustup self update` を明示的に実行する。Linux の draw.io を pin どおりに入れ直す場合は、既存パッケージを `sudo apt-get remove drawio` で削除し、後述の手順で `run_once` の状態を消して `chezmoi apply` を実行する。Microsoft apt リポジトリの鍵や suite を更新した場合も、同じ再実行が必要になる。

最低限の確認:

```bash
shellcheck install.sh
sed '/^[[:space:]]*{{/d' home/run_once_before_10-install-packages.sh.tmpl | shellcheck -e SC1091 -
sed '/^[[:space:]]*{{/d' home/run_once_before_10-install-packages.sh.tmpl | bash -n
sed '/^[[:space:]]*{{/d' home/run_once_before_20-install-mise.sh.tmpl | bash -n
sed '/^[[:space:]]*{{/d' home/run_once_after_10-setup-shell.sh.tmpl | shellcheck -e SC2034 -
sed '/^[[:space:]]*{{/d' home/run_once_after_10-setup-shell.sh.tmpl | bash -n
sed '/^[[:space:]]*{{/d' home/run_once_after_30-install-tools.sh.tmpl | shellcheck -
sed '/^[[:space:]]*{{/d' home/run_once_after_30-install-tools.sh.tmpl | bash -n
```

## このリポジトリを Dev Container で開発する

`.devcontainer/devcontainer.json` は、このリポジトリ自体を開発するための構成である。dotfiles を任意のプロジェクトの Dev Container へ適用する手順（`README.md` の「Dev Container (ローカル)」節）とは別のものを指す。

dotfiles は `devcontainer.json` から適用しない。VS Code の Dotfiles ユーザ設定は `README.md` の「Dev Container (ローカル)」節に従う。この設定がないコンテナにはテストに必要なツールが入らない。

VS Code の Dev Containers 拡張は Dotfiles セットアップコマンドへ `REMOTE_CONTAINERS=true` を渡す。chezmoi は初期化時にこの値を `.devcontainer` として設定へ保存する。統合ターミナルでは `REMOTE_CONTAINERS` が未設定の場合があるため、ターミナルの環境変数だけで初期化時の判定を再検証しない。

Dev Container と Codespaces の Copilot sandbox は受け入れ条件に含めない。ツール管理は通常の Linux と同じ `home/dot_config/mise/config.toml.tmpl`、`private_mise.lock`、mise 導入スクリプト、更新手順を使う。Dev Container だけは作成時の GitHub 未認証を避けるため、同じ config と lockfileによるツール導入を起動後へ遅らせる。

```bash
devcontainer up --workspace-folder .
```

コンテナ起動後に次を実行する。

```bash
gh auth login
GITHUB_TOKEN=$(gh auth token) mise install --yes
chezmoi apply
```

最後の `chezmoi apply` は、コンテナ作成時に `gh` の認証やツール導入を待って終了した `run_after` 処理を再実行する。

ホストの npm 設定と資格情報はコンテナへ自動継承しない。公式レジストリへ接続できない場合の確認と設定は、[`troubleshooting.md`](troubleshooting.md#dev-container-から-npm-registry-へ接続できない) を参照する。

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
