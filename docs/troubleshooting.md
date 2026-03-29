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
