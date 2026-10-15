# ADR-038: Windows sandbox で uv.toml だけを読み取り専用にする

## Status

Accepted

## Context

Windows の Copilot sandbox は `allowDevToolAccess` により一部の開発ツール関連パスを許可するが、uv の `%APPDATA%\uv\uv.toml` は自動許可に含まれない。uv がこの設定を読むには、Copilot user sandbox policy から読み取り許可を与える必要がある。`readonlyPaths` は uv だけでなく sandbox 内のすべてのプロセスに適用される。

CLI 1.0.99-0 と2026年10月15日時点の runtime source（commit `163d5cd15b3a34e74a6bd09ca27125e1a68bd85d`）で、Windows `allowDevToolAccess` がこのファイルを許可しないことと、別の自動許可がないことを確認した（[developer-tool access grants](https://github.com/github/copilot-agent-runtime/blob/163d5cd15b3a34e74a6bd09ca27125e1a68bd85d/src/runtime/src/sandbox_pure/dev_tool_access.rs#L1094-L1097)）。公開ユーザー向け文書での確認はできていない。

## Decision

Windows の sandbox 設定同期はユーザーの `%APPDATA%\uv\uv.toml` の絶対パスだけを `readonlyPaths` に追加する。親の `uv` ディレクトリは許可せず、ファイルの存在や内容を確認しない。ほかの環境と既存 policy entry は変更しない。

## Consequences

- sandbox 内の全 process がこのファイルを読み取れるが、書き込めない。
- sandbox の同期は既存の読み取り許可を保持し、同じファイル path を重複して追加しない。
- ADR-026 の「共有 `uv.toml` を追加許可しない」という判断を、Windows のこのファイルに限って置き換える。
