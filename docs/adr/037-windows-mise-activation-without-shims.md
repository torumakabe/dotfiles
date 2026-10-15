# ADR-037: Windows の mise activation は shim を追加しない

## Status

Accepted

## Context

Windows の PowerShell profile は `mise activate pwsh` を使う。既定では activation が shim を PATH の先頭に追加するが、Copilot sandbox 内では mise shim が設定を解決できず、sandboxed MCP の `npx` と PowerShell tool の `uv` が失敗した。Windows の既存 User PATH には mise が管理するツールの実体ディレクトリが同期されている。

CLI 1.0.99-0 と mise 2026.10.9 で、一時的に `MISE_ACTIVATE_SHIMS=false` を設定した子 PowerShellから Copilot を起動した。sandbox を有効にしたまま Azure MCP の初期化と sandbox PowerShell tool の uv 0.13.0 実行が成功した。適用後の通常起動はまだ確認していない。

## Decision

Windows 用 mise 設定に `activate_shims = false` を追加する。mise が追加する導入済みツールの bin directory は PATH に維持する。

## Consequences

- Windows の対話 PowerShell とそこから起動する子プロセスは、導入済みツールを shim でなく実体から解決する。
- shim を必要とする未導入または lazy install のツールは、`mise install` または `mise exec` で利用する。
- macOS と Linux の mise 設定は変わらない。
- chezmoi 適用後の通常起動で Azure MCP と sandbox 内 uv を確認する必要がある。
