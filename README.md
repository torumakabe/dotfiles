# dotfiles

Cross-platform dotfiles managed by [chezmoi](https://www.chezmoi.io/).

Linux / macOS / WSL / Windows / Codespaces / Dev Container で、できるだけ同じ運用感を保つための dotfiles である。設定ファイルは `chezmoi` で管理し、開発ツールはOSのパッケージマネージャーやツールごとの公式導入経路でそろえる。GitHub Copilot CLI 向けの指示、フック、スキルも同じリポジトリで管理する。

## このリポジトリが扱うもの

- **設定ファイルの配布**: `chezmoi` テンプレートで OS ごとの差分を吸収する
- **ツールの版管理**: `home/.chezmoidata.toml` に取得元、固定版または最低版、配布物の検証情報を宣言する
- **Copilot CLI の共通設定**: カスタム指示、フック、スキルを管理する
- **安全寄りの既定値**: `gitleaks` の pre-commit フックと Copilot Guard を組み込む

詳細は [`docs/architecture.md`](docs/architecture.md) と [`docs/copilot-cli.md`](docs/copilot-cli.md) を参照。

## 対応環境

| 環境 | セットアップ | 補足 |
|------|------------|------|
| Linux / macOS / WSL | [Linux / macOS / WSL](#linux--macos--wsl) | macOS は Apple Silicon のみ。WSL は初回 `windowsUser` 入力が必要 |
| GitHub Codespaces | [GitHub Codespaces](#github-codespaces) | 非対話セットアップのため一部設定を省略 |
| Dev Container (ローカル) | [Dev Container](#dev-container-ローカル) | 起動後にGitHub認証と必要なセットアップを再適用 |
| Windows | [Windows](#windows) | `copilot` は DSC + winget で導入。ARM64の互換実行は[ワークアラウンド](.github/copilot-instructions.md#ワークアラウンド定期チェック対象)を参照 |

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

Copilot local sandbox の初回値、設定保持、確認手順は [`docs/operations.md`](docs/operations.md#copilot-local-sandbox-の既定値) を参照。

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
chezmoi apply
```

`chezmoi apply` は、認証やツール導入を待っていたセットアップ処理を再実行する。各ツールの導入元と再適用の扱いは [`docs/operations.md`](docs/operations.md#ツールの管理境界) を参照。

このリポジトリ自体を Dev Container で開発する場合は `.devcontainer/devcontainer.json` を使う。構成の意図と起動後の手順は [`docs/operations.md`](docs/operations.md#このリポジトリを-dev-container-で開発する) を参照。

### Windows

```powershell
winget install twpayne.chezmoi
chezmoi init torumakabe
winget configure -f "$(chezmoi source-path)\..\reference\windows\configuration.dsc.yaml"
```

DSC は Copilot CLI と GitHub CLI を含む Windows パッケージを導入する。完了後は PowerShell を開き直し、`gh` を現在の PATH へ反映する。その後に dotfiles を初回適用する。`chezmoi apply` は `home/.chezmoidata.toml` の宣言に従って残りのツールを導入し、直接導入したランタイムの専用ディレクトリをユーザー `Path` へ登録する。既存プロセスは変更前の `Path` を保持するため、適用後に PowerShell を開き直す。GUI アプリへ反映されない場合は、サインアウトまたは OS の再起動後に確認する。

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

## 日常操作

`chezmoi` 管理下のファイルはホーム側を直接編集せず、`chezmoi edit` かソース側の編集を使う。

```bash
chezmoi edit ~/.zshrc
chezmoi diff
chezmoi apply
chezmoi update
```

各ツールの導入元と更新方法は [`docs/operations.md`](docs/operations.md) を参照。

## 詳細ドキュメント

- [`docs/operations.md`](docs/operations.md): ツールの管理境界、更新手順、pre-commit フック管理、`run_once_*` の再実行
- [`docs/architecture.md`](docs/architecture.md): ディレクトリ構造、設計判断、プラットフォーム分岐、Copilot Guard の構成
- [`docs/copilot-cli.md`](docs/copilot-cli.md): Copilot CLI の管理対象、フック、`copilot-guardrails`、監査ログ
- [`docs/troubleshooting.md`](docs/troubleshooting.md): よくある失敗と復旧手順
