# ADR-030: Copilot sandbox の uv は専用 cache を使う

## Status

Accepted

## Context

Copilot runtime cli-1.0.83 は通常の Python コマンドに対し、Linux の `~/.cache/uv`、macOS の `~/Library/Caches/uv`、Windows の `%LOCALAPPDATA%\uv\cache` を read-only grant として追加する。これは利用者の package cache を sandbox 内の処理から保護する設計だが、uv は通常の `uv run` でも cache 内に一時ファイルと lock を作成する。

WSL2 の built-in shell では、ADR-029 の mise data root grant 適用後に 43 コマンドすべてが実体パスへ解決し、代表 9 コマンドの実行にも成功した。一方、`uv run --no-project -- python --version` は `~/.cache/uv/.tmp...` の作成時に read-only filesystem エラーで終了した。単独の shell tool callでも同じ結果となり、複合コマンドの操作範囲判定による差ではなかった。

利用者設定の `readwritePaths` へ同じ uv cache path を追加するだけでは解決しない。cli-1.0.83 の `resolve_readonly_grants` は developer-tool cache の read-only grant を `ReadonlySource::Other` として保持し、同じ path の read-write grant があっても削除しない。後続の `github/copilot-agent-runtime#19014` も、`UV_CACHE_DIR` などで移動した cache に既定値と同じ read-only access を与える。このため、host process の環境変数や uv の global config で cache を移動しても、後続版では移動先が再び read-only になる。

Windows sandbox は `LOCALAPPDATA` を AppContainer 配下へ変更する。`github/copilot-agent-runtime#18974` では、変更後の一時領域と cache 内でファイル作成後の rename が拒否される問題が報告されている。host の既定 cache を policy へ追加するだけでは、uv が変更後の `LOCALAPPDATA` を参照するため、host と sandbox で利用する directory が一致しない。

uv は `UV_CACHE_DIR` を公式の cache directory override として提供する。preToolUse hook の `modifiedArgs` は後続 hook と実行対象の shell command へ引き継がれる。runtime の developer-tool cache 検出は host process の環境と利用者の tool config を参照し、shell command 内で設定する環境変数は参照しない。この差を使うと、sandbox policy で書き込みを許可した Copilot 専用 cache を uv に指定できる。

## Decision

preToolUse hook は `node-global-enforcer.py`、`uv-enforcer.py`、`copilot-guard.py` の順で実行する。`uv-enforcer.py` は許可する bash と PowerShell の command に、`modifiedArgs` を使って `UV_CACHE_DIR` の設定を追加する。Node.js と Python の実行規則は変更前の command を検査し、最後の `copilot-guard.py` は変更後の command を検査する。`copilot-guard.py` が確認を要求する場合も、先行 hook の command 変更は維持される。

| OS | Copilot 専用 uv cache |
|---|---|
| macOS | `~/Library/Caches/github-copilot/uv` |
| Linux、WSL、Codespaces、Dev Container | `${XDG_CACHE_HOME:-~/.cache}/github-copilot/uv` |
| Windows | `%LOCALAPPDATA%\GitHubCopilot\uv` |

Copilot sandbox の設定同期は同じ directory を `sandbox.userPolicy.filesystem.readwritePaths` へ追加し、directory を作成してから settings を書き込む。host の `UV_CACHE_DIR` と uv の global config は変更しない。command hook 自身は sandbox 外で動作するため、従来どおり host の uv cache を使う。

同じ path が既存の `readwritePaths` にあれば重複追加しない。`readonlyPaths` または `deniedPaths` の entry が同じ path か親 directory を指す場合は、既存の制限を自動的に解除せず、settings を書き換える前にエラーで停止する。管理する `github-copilot` directory とその `uv` directory が symbolic link または Windows の reparse point である場合も、意図しない対象への write grant を防ぐため停止する。read-write grant は uv cache directory だけを対象とし、cache home 全体や mise data rootには広げない。

hook 設定は session 開始時に読み込まれるため、適用後は Copilot CLI を再起動する。

## Consequences

- 通常の `uv run`、`uv sync`、`uv pip` は、sandbox 内で Copilot 専用 uv cache に必要な一時ファイルと lock を作成できる。
- 書き込み許可は uv cache に限定され、mise data root と他の package manager cache はread-onlyのまま維持される。
- host の uv cache と設定は変更せず、sandbox shell だけが専用 cache を使う。
- shell command 全体へ環境変数を設定するため、command 内で間接的に uv を起動する場合にも同じ cache を使う。command 自身が後から `UV_CACHE_DIR` を変更した場合は、その指定が優先される。
- 通常運用では古い Copilot 専用 uv cache path の entry を自動削除しない。この回避策を撤去するときは、リポジトリが管理する namespaced literal の完全一致 entry を削除する policy migration を実施する。
- WSL2 では commit `0c35b02` の適用後、43コマンドがすべて期待する mise 実体へ解決し、Copilot 専用 cache を使う `uv run --no-project -- python --version` が終了コード0で成功した。Windows では hook の command 変更と policy の単体テストを行うが、ProcessContainer での `uv run` 成功は実機検証まで未確認として扱う。

この回避策の撤去条件と対象範囲は、`.github/copilot-instructions.md` の「ワークアラウンド（定期チェック対象）」を参照し、本 ADR には重複して記載しない。
