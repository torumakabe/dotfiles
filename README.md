# dotfiles

Cross-platform dotfiles managed by [chezmoi](https://www.chezmoi.io/) + [mise](https://mise.jdx.dev/).

Linux / macOS / WSL / Windows / Codespaces / Dev Container で、できるだけ同じ運用感を保つための dotfiles である。設定ファイルは `chezmoi` で管理し、開発ツールのバージョンは `mise` でそろえ、GitHub Copilot CLI 向けの指示・フック・スキルも同じリポジトリで管理する。

## このリポジトリが扱うもの

- **設定ファイルの配布**: `chezmoi` テンプレートで OS ごとの差分を吸収する
- **ツールバージョンの固定**: `mise` と lockfile で取得元と版をそろえる
- **Copilot CLI の共通設定**: カスタム指示、フック、スキルを管理する
- **安全寄りの既定値**: `gitleaks` の pre-commit フックと Copilot Guard を組み込む

詳細は [`docs/architecture.md`](docs/architecture.md) と [`docs/copilot-cli.md`](docs/copilot-cli.md) を参照。

## 対応環境

| 環境 | セットアップ | 補足 |
|------|------------|------|
| Linux / macOS / WSL | [Linux / macOS / WSL](#linux--macos--wsl) | macOS は Apple Silicon のみ。WSL は初回 `windowsUser` 入力が必要 |
| GitHub Codespaces | [GitHub Codespaces](#github-codespaces) | 非対話セットアップのため一部設定を省略 |
| Dev Container (ローカル) | [Dev Container](#dev-container-ローカル) | `mise install --yes` は起動後に手動実行 |
| Windows | [Windows](#windows) | `copilot` は DSC + winget で導入 |

## クイックスタート

### Linux / macOS / WSL

```bash
git clone https://github.com/torumakabe/dotfiles.git ~/dotfiles
cd ~/dotfiles
./install.sh
```

初回実行時に次を聞かれる。

- **Windows username**: WSL のみ。1Password の WSL 連携パスに使う
- **Corp username**: 任意。企業用 Git 設定に使う

`mise install` がレート制限で失敗した場合は [`docs/operations.md`](docs/operations.md#mise-の保守) を参照。

### GitHub Codespaces

GitHub の dotfiles リポジトリに登録すると自動適用される。

- `corpUser` / `windowsUser` の入力は省略される
- 1Password SSH エージェントが使えないため、コミット署名は自動で無効化する

参考: [Codespaces docs](https://docs.github.com/en/codespaces/setting-your-user-preferences/personalizing-github-codespaces-for-your-account#dotfiles)

### Dev Container (ローカル)

VS Code の **Dotfiles** 設定で次を指定する。

- **Repository**: `torumakabe/dotfiles`
- **Install Command**: `install.sh`

コンテナ起動後に手動で実行する。

```bash
gh auth login
GITHUB_TOKEN=$(gh auth token) mise install --yes
chezmoi apply
```

`mise install` は作成時にはスキップする。最後の `chezmoi apply` は、認証やツール導入を待っていたセットアップ処理を再実行する。追加の注意点は [`docs/troubleshooting.md`](docs/troubleshooting.md#dev-container-で-mise-ツールが入っていない) を参照。

このリポジトリ自体を Dev Container で開発する場合は `.devcontainer/devcontainer.json` を使う。構成の意図と起動後の手順は [`docs/operations.md`](docs/operations.md#このリポジトリを-dev-container-で開発する) を参照。

### Windows

```powershell
winget install twpayne.chezmoi
chezmoi init torumakabe
winget configure -f "$(chezmoi source-path)\..\reference\windows\configuration.dsc.yaml"
```

DSC 完了後は PowerShell を開き直し、`gh` と `mise` を現在の PATH へ反映する。その後に dotfiles を初回適用する。`chezmoi apply` は mise lockfile に従って残りのツールも導入する。

```powershell
gh auth login
chezmoi apply
```

PowerShell Profile のローダー設定が未追加なら、dotfiles の初回適用後に次を実行する。

```powershell
if (!(Test-Path $PROFILE)) { New-Item -Path $PROFILE -Type File -Force }
$legacyLine = '. "$env:USERPROFILE\PowerShell_profile.ps1"'
$line = 'if (Test-Path "$env:USERPROFILE\PowerShell_profile.ps1") { . "$env:USERPROFILE\PowerShell_profile.ps1" }'
if (!(Select-String -Path $PROFILE -SimpleMatch $legacyLine -Quiet) -and
    !(Select-String -Path $PROFILE -SimpleMatch $line -Quiet)) {
    Add-Content -Path $PROFILE -Value $line
}
```

`copilot` は DSC 側で導入するため、Windows では `mise` の対象外である。

## 日常操作

`chezmoi` 管理下のファイルはホーム側を直接編集せず、`chezmoi edit` かソース側の編集を使う。

```bash
chezmoi edit ~/.zshrc
chezmoi diff
chezmoi apply
chezmoi update
```

`mise` 管理ツールの更新や lockfile 再生成は [`docs/operations.md`](docs/operations.md) を参照。

## 詳細ドキュメント

- [`docs/operations.md`](docs/operations.md): `mise` の更新、lockfile 再生成、pre-commit フック管理、`run_once_*` の再実行
- [`docs/architecture.md`](docs/architecture.md): ディレクトリ構造、設計判断、プラットフォーム分岐、Copilot Guard の構成
- [`docs/copilot-cli.md`](docs/copilot-cli.md): Copilot CLI の管理対象、フック、`copilot-guardrails`、監査ログ
- [`docs/troubleshooting.md`](docs/troubleshooting.md): よくある失敗と復旧手順
