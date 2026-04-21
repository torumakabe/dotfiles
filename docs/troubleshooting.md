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

## 非対話シェルで PATH が通らない

症状: Copilot CLI エージェント、IDE のタスク、`bash script.sh` などから `copilot`, `uv`, `node`, `kubectl`, `azd` などが `command not found` / `CommandNotFoundException`。

原因: `.zshrc` / `$PROFILE` は非対話シェルでは読まれない。macOS では加えて `/opt/homebrew/bin`（brew shellenv）が launchd 既定 PATH に含まれないため GUI 起動子プロセスでも brew 管理ツールが見えない。

### 確認

```bash
# Unix（login shell を新規に開いた直後）
echo "$PATH" | tr ':' '\n'
# 期待: ~/.local/share/mise/shims, ~/.local/bin, ~/go/bin が含まれる
# macOS なら /opt/homebrew/bin も含まれる
command -v copilot   # macOS: /opt/homebrew/bin/copilot, Linux: ~/.local/bin/copilot
command -v uv        # ~/.local/share/mise/shims/uv
```

```powershell
# Windows
(Get-Command uv).Source
[Environment]::GetEnvironmentVariable('Path', 'User') -split ';' | Select-String 'mise\\shims'
```

### 復旧

設計は [`docs/architecture.md`](architecture.md#path-管理非対話シェル対応) を参照。新規環境で反映されていない場合:

- **Unix**: `chezmoi apply` で `~/.profile` と `~/.zprofile` が配置されるか確認。新規 login シェル（新しい Terminal タブなど）を開くと有効化される
- **macOS GUI アプリ経由の bash**（例: GitHub Desktop の Copilot SDK、`bash --norc --noprofile` で起動）: `chezmoi apply` 時に `run_onchange_after_06-link-mise-shims.sh` が走り、mise shim が `~/.local/bin` に symlink される。Copilot CLI を再起動すると反映される (GitHub Desktop 自体の再起動は不要)
  - 新規ツールを Copilot CLI セッションで使いたい場合は `home/run_onchange_after_06-link-mise-shims.sh.tmpl` の `TOOLS` 配列に追加して `chezmoi apply` を実行
  - 無効化したい場合は `rm ~/.local/bin/<tool>` (symlink のみが削除される)
- **Windows**: `run_once_after_05-setup-mise-shims-path.ps1` を再実行する

```bash
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

新規シェルを開き直してから再確認する。
