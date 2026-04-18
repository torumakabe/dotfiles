# Troubleshooting

README に載せない復旧手順だけをまとめる。一般的な `chezmoi` / `mise` の仕様説明は各公式ドキュメントを参照。

## `warning: config file template has changed`

`.chezmoi.toml.tmpl` の更新後に出る。設定を再生成する。

```bash
chezmoi init torumakabe
```

リポジトリ名を省略すると、ソースディレクトリが空になり `chezmoi update` が動かなくなる。必ず `torumakabe` を指定する。

## `mise install` が部分失敗する

まず [`docs/operations.md`](operations.md#github-api-と-github_token) の手順で `GITHUB_TOKEN` を付けて再実行する。

lockfile 側の問題なら再生成する。

```bash
mise ls --missing
rm ~/.config/mise/mise.lock
GITHUB_TOKEN=$(gh auth token) mise lock --global --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
mise install
```

## `run_once_*` スクリプトの warning / error

実行順と役割は [`docs/architecture.md`](architecture.md#run_once_-スクリプトの実行順と依存関係) を参照。

- **warning で継続**: shell 設定の一部、`mise install` 後の任意ツール、追加ツール導入の失敗
- **error で停止**: Oh My Zsh の clone、Docker 本体導入など継続に必要な処理

warning は標準エラーに表示される。表示されたコマンドを手動で再実行して復旧する。

## `run_once_*` スクリプトが sudo を要求して停止する

Codespaces 以外ではパッケージ導入に sudo が必要である。パスワードを入力するか、sudoers を設定する。

## Dev Container で mise ツールが入っていない

コンテナ作成時は `mise install` を自動実行しない。README の Dev Container セクション、または [`docs/operations.md`](operations.md#github-api-と-github_token) の手順で起動後に実行する。

## 非対話シェルで mise 管理ツールが見つからない

症状: Copilot CLI エージェント、IDE のタスク、`bash script.sh` などから `uv`, `node`, `kubectl` などが `command not found` / `CommandNotFoundException`。

原因: `mise activate` は `.zshrc` / `$PROFILE` 経由でのみ PATH を注入するが、これらは非対話シェルでは読まれない。

### 確認

```bash
# Unix
command -v uv     # shims 配下なら OK
echo "$PATH" | tr ':' '\n' | grep mise/shims
```

```powershell
# Windows
(Get-Command uv).Source
[Environment]::GetEnvironmentVariable('Path', 'User') -split ';' | Select-String 'mise\\shims'
```

### 復旧

設計は [`docs/architecture.md`](architecture.md#mise-shims-による非対話シェル対応) を参照。新規環境で反映されていない場合:

- **Unix**: `chezmoi apply` で `~/.zprofile` が配置されるか確認。新規 login シェル（新しい Terminal タブなど）を開くと有効化される
- **Windows**: `run_once_after_05-setup-mise-shims-path.ps1` を再実行する

```bash
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

新規シェルを開き直してから再確認する。
