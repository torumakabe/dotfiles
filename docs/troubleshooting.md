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

lockfile 側の問題なら再生成する。

```bash
mise ls --missing
rm ~/.config/mise/mise.lock
GITHUB_TOKEN=$(gh auth token) mise lock --global --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
mise install
```

### Windows で `core:dotnet` の検証に失敗する

症状は、インストールスクリプトが SDK を配置した後、`dotnet --list-sdks` が system 側の SDK だけを返し、次のエラーで終了することである。

```text
dotnet SDK <version> was not found in `dotnet --list-sdks` output
```

Windows 用の mise 設定は、インストール時だけ mise の共有 dotnet root を `DOTNET_ROOT` と PATH の先頭へ設定する。設定を配り直し、同じ backend とバージョンを強制的に再インストールする。

```powershell
chezmoi apply "$HOME\.config\mise\config.toml"
mise install --force dotnet
mise ls dotnet
mise which dotnet
& (mise which dotnet) --version
```

`mise ls dotnet` に `(missing)` がなく、`mise which dotnet` が `%LOCALAPPDATA%\mise\dotnet-root\dotnet.exe` を返し、最後のコマンドが設定済み SDK のバージョンを表示すれば復旧している。

## `mise.lock has changed since chezmoi last wrote it?` と聞かれる

`chezmoi status` が `MM .config/mise/mise.lock` を示し、`chezmoi apply` が上のプロンプトを出す。Codespaces のような TTY の無い環境では `could not open a new TTY` で停止する。

デプロイ済みの lockfile に、意図しないプラットフォームのエントリが加わった状態である。`chezmoi diff ~/.config/mise/mise.lock` で追加された行を確認する。`linux-x64-musl` や `windows-x64-baseline` のようなエントリが増えていれば、`lockfile_platforms` が効かないまま auto-lock が走ったことを意味する（[ADR-021](adr/021-mise-lockfile-platforms.md)）。

原因は二つある。まず mise のバージョンを確認する。

```bash
mise --version
```

`lockfile_platforms` は mise `2026.4.8` 以降が必要である。これより古い場合、設定は警告なく無視される。既存の mise がある端末では `run_once_before_20-install-mise.sh` がバージョンを問わず何もしないため、自分で更新する。

```bash
mise self-update        # macOS/Homebrew は brew upgrade mise、Windows は mise-self-upgrade
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

## 非対話シェルで PATH が通らない

症状: Copilot CLI エージェント、IDE タスク、`bash script.sh` から `copilot` / `uv` / `node` / `kubectl` / `azd` が `command not found`。

設計の全体像は [`docs/architecture.md`](architecture.md#path-管理非対話シェル対応) を参照。復旧は以下を試す:

- **Unix**: `chezmoi apply` で `~/.profile` 系が配置されているか確認。新規 login シェル（新しい Terminal タブ）で有効化
- **macOS GUI アプリ経由**（GitHub Desktop の Copilot SDK 等）: `chezmoi apply` で `run_onchange_after_21-link-mise-shims.sh` が走り mise shim が `~/.local/bin` に symlink される。Copilot CLI を再起動すれば反映（除外リストの変更は `home/run_onchange_after_21-link-mise-shims.sh.tmpl` で編集）
- **Windows**: `run_once_after_05-setup-mise-shims-path.ps1` を再実行

それでも反映されないときは state を消して再実行:

```bash
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

確認コマンド:

```bash
echo "$PATH" | tr ':' '\n'   # ~/.local/share/mise/shims, ~/.local/bin, ~/go/bin が含まれること
command -v copilot uv
```

```powershell
(Get-Command uv).Source
[Environment]::GetEnvironmentVariable('Path', 'User') -split ';' | Select-String 'mise\\shims'
```

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

対策は導入済み。判定は `~/.local/bin/copilot` の実体で行う。既存のコンテナでは次で復旧する。

```bash
curl -fsSL https://gh.io/copilot-install | bash   # ~/.local/bin/copilot へ導入
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

本リポジトリの command hook は `MISE_ENABLE_TOOLS=uv` を設定し、mise の解決対象を `uv` に限定する。`uv` の未導入版は自動導入されるが、dotnet など他ツールの missing 状態は hook 起動時に解決しない。標準エラーに他ツールのインストールログが出る場合は、`~/.copilot/hooks/hooks.json` が最新か確認し、`chezmoi apply` で配り直す。

上のフィルターで何も表示されない場合は、CLI の更新でイベント形式が変わった可能性がある。`Where-Object { $_.type -eq 'hook.end' }` まで条件を緩め、直近イベントの `data` 全体を確認する。
