# dotfiles

Cross-platform dotfiles managed by [chezmoi](https://www.chezmoi.io/) + [mise](https://mise.jdx.dev/).

このリポジトリは、Linux / macOS / WSL / Windows / Codespaces / Dev Container で、同じ運用感と安全なデフォルトを維持するための dotfiles である。`chezmoi` で設定ファイルをテンプレート管理し、`mise` で開発ツールのバージョンをそろえ、OS ごとの差分は最小限の分岐に閉じ込めている。コーディングエージェント向けの共通化は、GitHub Copilot CLI を前提にカスタム指示、フック、スキルを整備している。

## 特徴と価値

- **1つのソースで複数環境を管理**: `chezmoi` のテンプレートで、プラットフォームごとの差分を吸収しながら設定を一元管理している
- **ツールチェーンを再現しやすい**: `mise` と lockfile で、開発ツールのバージョンと取得元をそろえやすい構成である
- **GitHub Copilot CLI 向け設定を共通化**: カスタム指示、フック、スキルを dotfiles として管理している
- **安全なデフォルト**: `gitleaks` を組み込んだ `git pre-commit` フックと Copilot CLI の `preToolUse` フックにより、コミット前とエージェント実行時のガードをそろえている。エージェント向けフックは秘匿ファイルへのアクセス、環境変数の読み取り、許可外 URL への送信を自動拒否する（[詳細](docs/copilot-cli.md#セキュリティフック)）
- **制約の多いコンテナ環境でも破綻しにくい**: 非対話での作成やホスト側ツールにアクセスできないケースを考慮し、必要な分岐やフォールバックを組み込んでいる

## 対応環境

| 環境 | セットアップ | 注意点 |
|------|------------|--------|
| Linux / macOS | [クイックスタート → Linux / macOS / WSL](#linux--macos--wsl) | — |
| WSL | [クイックスタート → Linux / macOS / WSL](#linux--macos--wsl) | 1Password パスが Windows 側、初回 `windowsUser` 入力が必要 |
| GitHub Codespaces | [クイックスタート → GitHub Codespaces](#github-codespaces) | `corpUser` 未設定 |
| Dev Container (ローカル) | [クイックスタート → Dev Container](#dev-container-ローカル) | 初回 `mise install --yes` を手動実行 |
| Windows | [クイックスタート → Windows](#windows) | — |

## クイックスタート

### Linux / macOS / WSL

以下の例では `~/dotfiles` に clone しているが、clone 先は任意でよい。`install.sh` は検証済みの `chezmoi` リリースを展開した後、`chezmoi init --apply` でリポジトリを chezmoi のソースディレクトリ（`~/.local/share/chezmoi`）へ改めて clone し、設定ファイルをホームに配置する。最初の clone は `install.sh` を取得するためだけに使う。

```bash
git clone https://github.com/torumakabe/dotfiles.git ~/dotfiles
cd ~/dotfiles
./install.sh
```

初回実行時にプラットフォーム検出と変数の入力プロンプトが表示される。

- **Windows username** (WSL のみ): 1Password の WSL 連携パスに使用
- **Corp username** (任意): 所属企業での Git ユーザー名。gitconfig に使用

`mise install` がレート制限で失敗した場合は、[`docs/operations.md` の `mise` セクション](docs/operations.md#mise-と-github-api)を参照してリトライする。

### GitHub Codespaces

自動適用される。GitHub の設定で dotfiles リポジトリとして登録するだけでよい。

参考: [Codespaces docs](https://docs.github.com/en/codespaces/setting-your-user-preferences/personalizing-github-codespaces-for-your-account#dotfiles)

制限事項:

- 非対話での作成のため `corpUser` / `windowsUser` のプロンプトはスキップされ、空文字になる（`.gitconfig-corp` は適用されない）
- コミット署名（`commit.gpgsign`）は自動で無効化される（1Password SSH エージェントが利用できないため）

Codespaces では GitHub の [GPG verification](https://docs.github.com/en/codespaces/managing-your-codespaces/managing-gpg-verification-for-github-codespaces) を有効にすることで、GitHub 管理の鍵による署名が可能である。

### Dev Container (ローカル)

任意のリポジトリの Dev Container で dotfiles を適用するケースである。VS Code の設定で dotfiles リポジトリを指定すると、コンテナ作成時に `install.sh` が自動実行される。

参考: [Personalizing with dotfile repositories](https://code.visualstudio.com/docs/devcontainers/containers#_personalizing-with-dotfile-repositories)

1. VS Code の Settings → **Dotfiles** で以下を設定:
   - **Repository**: `torumakabe/dotfiles`
   - **Install Command**: `install.sh`
2. Dev Container を作成すると `install.sh` → `chezmoi init --apply` が自動実行される
3. コンテナ起動後にターミナルから手動で実行:

```bash
gh auth login
GITHUB_TOKEN=$(gh auth token) mise install --yes
```

制限事項:

- `mise install` はコンテナ作成時にスキップされる。コンテナ起動後に手動実行する
- Docker, Go tools, draw.io などの追加ツール導入はスキップされる。必要ならベースイメージまたは Dev Container Feature 側で補う
- 非対話での作成のため `corpUser` / `windowsUser` は空文字になる
- コミット署名（`commit.gpgsign`）は自動で無効化される（1Password SSH エージェントが利用できないため）

### Windows

1. chezmoi インストール: `winget install twpayne.chezmoi`
2. 設定適用: `chezmoi init --apply torumakabe`
3. GUI アプリ: `winget configure -f "$(chezmoi source-path)\..\reference\windows\configuration.dsc.yaml"`
4. PowerShell Profile のローダー設定（初回のみ）:

```powershell
if (!(Test-Path $PROFILE)) { New-Item -Path $PROFILE -Type File -Force }
$line = '. "$env:USERPROFILE\PowerShell_profile.ps1"'
if (!(Select-String -Path $PROFILE -SimpleMatch $line -Quiet)) {
    Add-Content -Path $PROFILE -Value $line
}
```

5. ツールインストール:

```powershell
gh auth login
$env:GITHUB_TOKEN = (gh auth token); mise install; $env:GITHUB_TOKEN = $null
```

## 日常操作

### 何をどこで管理するか

| 分類 | 例 | 編集方法 |
|------|----|----------|
| **chezmoi 管理** | `.gitconfig`, `.zshrc`, `.config/mise/config.toml`, `.copilot/` | `chezmoi edit` でソースを編集 → `chezmoi apply` |
| **mise 管理** | Go, Node, Terraform などのバージョン | `.config/mise/config.toml` を更新 → `mise install` |
| **手動管理** | `reference/windows/` 配下 | 直接編集して git commit |
| **リポジトリメタ情報** | `README.md`, `.github/copilot-instructions.md` | 直接編集して git commit |

**重要**: chezmoi 管理下のファイルを直接編集しても、次回の `chezmoi apply` で上書きされる。永続化するには `chezmoi edit` またはソース側の編集を使う。

### よく使うコマンド

| やりたいこと | コマンド |
|--------------|----------|
| 設定ファイルを編集 | `chezmoi edit ~/.zshrc` |
| 変更を反映 | `chezmoi apply` |
| 適用前の差分を見る | `chezmoi diff` |
| 生成結果を確認 | `chezmoi cat ~/.gitconfig` |
| リモートの変更を取り込む | `chezmoi update` |
| mise 管理ツールをまとめて更新 | `mise-upgrade` |

### 典型的な作業フロー

設定を変えるとき:

```bash
chezmoi edit ~/.zshrc
chezmoi diff
chezmoi apply
```

リモートの変更を反映するとき:

```bash
chezmoi update
```

`mise` 管理ツールを更新するとき:

```bash
mise-upgrade
```

`mise-upgrade` は `gh auth token` の一時取得、`mise upgrade`、`mise lock --platform`、`chezmoi re-add`、git commit + push までをまとめて実行するシェル関数である。詳細な手順や例外系は [`docs/operations.md`](docs/operations.md) を参照する。

## 詳細ドキュメント

- [`docs/operations.md`](docs/operations.md): 運用詳細、`mise` の追加・削除、lockfile 再構築、`git pre-commit` フックの追加・更新、`run_once_*` の扱い
- [`docs/architecture.md`](docs/architecture.md): ディレクトリ構造、主要な設計判断、`git pre-commit` フックの構造、プラットフォーム検出、Git `includeIf` 設計
- [`docs/copilot-cli.md`](docs/copilot-cli.md): Copilot CLI の管理対象ファイル、プラグイン、スキル、フックのテスト方法
- [`docs/troubleshooting.md`](docs/troubleshooting.md): よくあるエラーと復旧手順
