# Troubleshooting

README に載せきらない復旧手順をまとめる。

## `warning: config file template has changed`

`.chezmoi.toml.tmpl` が更新された場合に表示される。設定を再生成する。

```bash
chezmoi init torumakabe
```

> **注意**: リポジトリ名を省略すると、ソースディレクトリが空になり `chezmoi update` が動かなくなる。必ず `torumakabe` を指定すること。

## `mise install` が部分失敗する

GitHub API のレート制限が原因の場合は、[`docs/operations.md`](operations.md#mise-と-github-api) の手順でトークンを設定してリトライする。

lockfile にないツールがある場合は lockfile を再生成する。

```bash
mise ls --missing
rm ~/.config/mise/mise.lock
GITHUB_TOKEN=$(gh auth token) mise lock --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64
mise install
```

## `run_once_` スクリプトの warning / error

warning として継続するもの:

- `run_once_after_10-setup-shell.sh`: デフォルトシェルを zsh に変更できない場合
- `run_once_after_20-mise-install.sh`: `mise install` 後の一部ツールが未導入のまま残る場合、または状態確認・認証なしリトライの一部が失敗した場合
- `run_once_after_30-install-tools.sh`: 追加の Go ツール、macOS の cask、Linux の draw.io など任意ツールの導入に失敗した場合

error として停止するもの:

- Oh My Zsh の clone、Docker 本体の導入など、セットアップ継続に必要な主要処理

warning は標準エラーに明示表示される。表示されたコマンドを手動で再実行して復旧できる。

## `run_once_` スクリプトが sudo を要求して停止する

Codespaces 以外の環境では、パッケージインストールに sudo が必要である。パスワードを入力するか、sudoers を設定する。

## Dev Container で mise ツールが入っていない

コンテナ作成時に `mise install` は自動スキップされる。README の Dev Container セクション、または [`docs/operations.md`](operations.md#mise-と-github-api) を参照して手動実行する。
