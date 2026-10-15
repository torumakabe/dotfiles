# ADR-035: Copilot CLI MCP servers を sandbox 対象にする

## Status

Accepted

## Context

ADR-026 の sandbox 設定を維持したまま、MCP server にも sandbox policy を適用する。
これにより、MCP の子プロセスにも sandbox credentials の mask 設定を適用できる。

## Decision

`sandboxMcpServers=true` とする。local MCP process は `sandbox.enabled=true` の session で sandbox 内に実行する。`sandboxLspServers=false` を含む他の dotfiles 設定は変更しない。ADR-026 の環境別 `sandbox.enabled` 初回値と明示設定保持の判断も維持する。

## Consequences

- local MCP server process に sandbox policy が適用される。
- MCP 子プロセスへ渡す環境変数の mask 対象は、利用者設定で管理する。
