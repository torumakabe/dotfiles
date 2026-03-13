# Operations Guide

`README.md` には日常的に使う手順だけを残し、このファイルには運用の詳細と非日常作業をまとめる。

## パッケージの管理

| 環境 | 管理ツール | 対象 |
|------|-----------|------|
| Linux / WSL | `apt` + `mise` | apt: OS パッケージ + Azure CLI、mise: 開発ツール |
| macOS | `brew` + `mise` | brew: OS パッケージ・GUI アプリ + Azure CLI、mise: 開発ツール |
| Codespaces / Dev Container | ベースイメージ / Feature + `mise` | Feature: Azure CLI など、mise: 開発ツール |
| Windows | `winget` (DSC) + `mise` | winget: GUI/CLI アプリ + Azure CLI、mise: 開発ツール |
| 全環境共通 | `uv` | Python スクリプト実行 |

> **Azure CLI**: mise ではなく各プラットフォームの公式パッケージマネージャーで管理する。Codespaces / Dev Container では devcontainer Feature を使う。

## chezmoi コマンドリファレンス

| コマンド | 参照先 | 用途 |
|----------|--------|------|
| `chezmoi init <repo>` | リモート | 初回セットアップ、構成テンプレート変更時の再初期化 |
| `chezmoi update` | リモート | `git pull` + `apply` を一括実行 |
| `chezmoi apply` | ローカル | ソース → ホームに反映 |
| `chezmoi diff` | ローカル | ソースとホームの差分表示 |
| `chezmoi cat <file>` | ローカル | テンプレート展開結果の確認 |
| `chezmoi edit <file>` | ローカル | ソースを編集 |
| `chezmoi add <file>` | ローカル | ホームの変更をソースに取り込み |

リモート参照は `init` と `update` のみである。変更を共有するには、chezmoi のソースディレクトリで `git commit` + `git push` する。

## 設定ファイルの編集

```bash
chezmoi edit ~/.zshrc

cd $(chezmoi source-path)/..
vim home/dot_zshrc.tmpl
chezmoi apply
```

## 変更の確認

```bash
chezmoi diff
chezmoi cat ~/.gitconfig
```

## 新しいファイルを chezmoi 管理下に追加

```bash
chezmoi add ~/.some-config
```

## mise 管理ツールの更新

シェル関数 `mise-upgrade`（`.zshrc` / `$PROFILE` で定義済み）が以下を一括実行する。

1. `gh auth token` で一時トークンを取得
2. `mise upgrade` で全ツールを最新化
3. `mise lock --platform` で全プラットフォームの lockfile を更新
4. `chezmoi re-add` で lockfile をソースに反映
5. git commit + push

```bash
mise-upgrade
```

初期構築直後は、現セッションにシェル設定が読み込まれていないことがある。使う前にターミナルを再起動するか、手動で読み込む。

- bash / zsh: `source ~/.zshrc`
- PowerShell: `. $PROFILE`

他の端末では `chezmoi update` で lockfile が同期され、`mise install` は lockfile の URL から直接ダウンロードする。

### 手動で実行する場合

`mise lock` は引数なしだと既定の 8 プラットフォーム（musl 含む）を対象にするため、**常に `--platform` を指定する**。

```bash
GITHUB_TOKEN=$(gh auth token) mise upgrade
GITHUB_TOKEN=$(gh auth token) mise lock --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
chezmoi re-add ~/.config/mise/mise.lock
cd $(chezmoi source-path)/.. && git add -A && git commit -m "chore: upgrade mise tools" && git push
```

```powershell
$env:GITHUB_TOKEN = (gh auth token); mise upgrade; mise lock --platform "linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64"; $env:GITHUB_TOKEN = $null
chezmoi re-add ~\.config\mise\mise.lock
cd (Join-Path (chezmoi source-path) ".."); git add -A; git commit -m "chore: upgrade mise tools"; git push
```

## mise のツール追加・削除

```bash
chezmoi edit ~/.config/mise/config.toml
GITHUB_TOKEN=$(gh auth token) mise install
GITHUB_TOKEN=$(gh auth token) mise lock --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
chezmoi re-add ~/.config/mise/config.toml
chezmoi re-add ~/.config/mise/mise.lock
```

PowerShell の場合は `$env:GITHUB_TOKEN = (gh auth token); <command>; $env:GITHUB_TOKEN = $null` で囲む。`--platform` の値は必ずクォートする。

## mise lockfile の再構築

以下の状況では lockfile を削除してから `--platform` 付きで再生成する。

- 新しいプラットフォームの端末を使い始める
- 不要なプラットフォームのエントリを除去したい
- lockfile が壊れた

```bash
rm ~/.config/mise/mise.lock
GITHUB_TOKEN=$(gh auth token) mise lock --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
chezmoi re-add ~/.config/mise/mise.lock
```

## Bootstrap / shell pin の更新

初期セットアップ系スクリプトは、上流の最新版をその場で実行せず、リリース番号・コミット・SHA256 をリポジトリ内に pin している。更新時は **バージョンの更新 → 公式チェックサムの照合 → スクリプト反映** の順で行う。

- `install.sh`
  - `CHEZMOI_VERSION` を更新
  - `chezmoi_<version>_checksums.txt` から利用中プラットフォーム分の SHA256 を更新
- `home/run_once_before_20-install-mise.sh.tmpl`
  - `MISE_VERSION` を更新
  - `SHASUMS256.txt` から利用中プラットフォーム分の SHA256 を更新
- `home/run_once_after_10-setup-shell.sh.tmpl`
  - `OH_MY_ZSH_COMMIT` を更新
  - `ZSH_COMPLETIONS_TAG` を安定版へ更新

更新後は最低限次を実行して差分を確認する。

```bash
shellcheck install.sh
sed '/^{{/d' home/run_once_before_20-install-mise.sh.tmpl | bash -n
sed '/^{{/d' home/run_once_after_10-setup-shell.sh.tmpl | bash -n
```

## mise と GitHub API

mise はツールのダウンロードに GitHub API を使う。未認証の場合、レート制限（60 req/hr）に抵触する可能性がある。

`gh` は mise より先にシステムパッケージとして導入される。認証後に `gh auth token` で `GITHUB_TOKEN` を取得できる。

```bash
gh auth login
GITHUB_TOKEN=$(gh auth token) mise install
```

```powershell
gh auth login
$env:GITHUB_TOKEN = (gh auth token); mise install; $env:GITHUB_TOKEN = $null
```

`run_once_after_20` は gh が認証済みなら `GITHUB_TOKEN` を自動設定する。初回セットアップで gh が未認証の場合は、セットアップ完了後に上記コマンドでリトライする。

`mise.lock` は各ツールのダウンロード URL とチェックサムを事前に解決したファイル。config.toml で `lockfile = true` を設定しており、`mise install` / `mise upgrade` ともに lockfile を自動更新する。

| 操作 | GitHub API | トークン |
|------|-----------|---------|
| `mise install`（lockfile あり） | 最小限 | 推奨 |
| `mise upgrade`（ツール更新） | 呼ぶ | 必要 |
| `mise lock`（lockfile 再生成） | 呼ぶ | 必要 |

注意事項:

- `GITHUB_TOKEN` を `.zshrc` や `$PROFILE` に常駐させない
- ツール追加時は `mise lock --platform` で全プラットフォーム分の lockfile を再生成してからコミットする

## git pre-commit フックの追加・更新

このリポジトリでは、グローバル `git pre-commit` フックを dotfiles の一部として配布している。フックは `gitleaks` による secret scan を実行した後、必要であれば各リポジトリ固有の `.git/hooks/pre-commit` へ処理を委譲する。

初回適用後に有効化を確認する場合:

```bash
git config --global core.hooksPath
```

想定される出力は `~/.config/git/hooks` である。

グローバルフック自体を更新した場合は、dotfiles 側を修正してから通常どおり反映する。

```bash
chezmoi edit ~/.config/git/hooks/pre-commit
chezmoi diff
chezmoi apply
```

新しい端末で `gitleaks` が未導入なら、`mise` で導入する。

```bash
mise install gitleaks
```

各リポジトリでローカルの `pre-commit` フックも併用したい場合は、従来どおり `.git/hooks/pre-commit` を配置してよい。グローバルフック側がそれを明示的に呼び出す構成である。

## run_once_ スクリプトの再実行

```bash
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

## run_once_ スクリプトの実行順と依存関係

このリポジトリでは、`run_once_before_*` → 通常のファイル適用 → `run_once_after_*` の順に処理される。さらに同じフェーズ内ではファイル名の数字順で実行される。

| 順序 | スクリプト | 役割 | 後続が依存している前提 |
|------|-----------|------|------------------------|
| 1 | `run_once_before_10-install-packages.sh` | OS パッケージを導入 | `git` / `zsh` が後続の shell setup と mise bootstrap までに使える |
| 2 | `run_once_before_20-install-mise.sh` | `mise` 自体を導入 | `run_once_after_20-mise-install.sh` 開始時点で `mise` コマンドが存在する |
| 3 | `run_once_after_10-setup-shell.sh` | Oh My Zsh / plugin / default shell を設定 | `git` / `zsh` は 1 で導入済み |
| 4 | `run_once_after_20-mise-install.sh` | `~/.config/mise/config.toml` と `mise.lock` を使ってツール本体を導入 | chezmoi による dotfiles 配置完了後に実行される |
| 5 | `run_once_after_30-install-tools.sh` | Docker, Go tools, GUI アプリなどの追加導入 | `mise install` 済みで `go` などのコマンドが PATH に存在する |

変更時は少なくとも次を確認すること。

- `before_` / `after_` の跨ぎを変えても、`mise` 設定ファイルや lockfile が生成される前に `mise install` しないこと
- `run_once_before_10-install-packages.sh` のパッケージ変更で、後続の前提を壊していないこと
- `run_once_after_10-setup-shell.sh` は非対話実行でも失敗しないこと
- `run_once_after_20-mise-install.sh` の retry / workaround を変える場合、Codespaces とローカル Dev Container の分岐を壊していないこと
- `run_once_after_30-install-tools.sh` の skip 条件を変える場合、Codespaces / Dev Container では引き続きベースイメージや Features 側で補う前提か確認すること
