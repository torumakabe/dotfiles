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

## shell 起動時に `mise WARN missing:` が出る

`mise upgrade` 等で `private_mise.lock` が更新された後、対応する `mise install` / `mise reshim` が走っていないと shim と install marker が古いまま残り、`mise hook-env` で `WARN missing:` が出る。Windows では rustup の `info: syncing channel updates ...` も併発する。

通常は `chezmoi apply` で `run_onchange_after_15-mise-sync-tools` フック（[ADR-013](adr/013-mise-lockfile-sync-hook.md)）が自動で同期する。手動で `mise uninstall` した等のケースで残った場合は次を実行する。

```bash
mise install
mise reshim
```

## `run_once_*` スクリプトの warning / error

実行順と役割は [`docs/architecture.md`](architecture.md#run_once_-スクリプトの実行順) を参照。

- **warning で継続**: shell 設定の一部、`mise install` 後の任意ツール、追加ツール導入の失敗
- **error で停止**: Oh My Zsh の clone、Docker 本体導入など継続に必要な処理

warning は標準エラーに表示される。表示されたコマンドを手動で再実行して復旧する。

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

## Copilot CLI: preToolUse フックが並列実行時にすり抜ける

症状: 短時間に複数のツール呼び出しが走った際、`copilot-guard.py` / `uv-enforcer.py` の deny が適用されず、ブロックすべき操作が実行される。

原因 (CLI v1.0.35 系で観測):

- **タイムアウト時の挙動は fail-open**: `timeoutSec` を超えても hook プロセスは kill されず、CLI 側が待機を打ち切って allow フォールバックし、遅れて届く deny は破棄される
- **hook 起動が逐次キュー化**: 同時に 5 件のツール呼び出しが来ても hook は 1.5〜4 秒間隔で順番に起動される。並列数が増えるほどキュー末尾が `timeoutSec` を超え、上記 fail-open が発動しやすい

対策 (本リポジトリで適用済み):

- `home/private_dot_copilot/hooks/hooks.json` の `timeoutSec` を preToolUse 30 秒 / postToolUse 15 秒に設定し、キューが長くなっても fail-open に落ちにくくする
- 上流の挙動変更を追跡する (`github/copilot-cli` の issue)

暫定回避:

- 高並列が予想される作業（一括コマンド送信など）では、1 応答内のツール呼び出し数を抑える
- deny すべき操作が通ってしまった場合は `~/.copilot/audit.jsonl`（成功ログ）/ `audit-denies.jsonl`（preToolUse deny）/ `audit-failures.jsonl`（tool handler error）で事後検出し、手動で巻き戻す
