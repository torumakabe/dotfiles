# ADR-037: Windows の mise activation は shim を追加しない

## Status

Accepted

## Context

Windows の PowerShell profile は `mise activate pwsh` を使う。mise shim は sandbox 内で設定を解決できず、
MCP や shell tool のコマンド起動に失敗する場合がある。mise 管理ツールの実体ディレクトリは
User PATH に同期されている。

## Decision

Windows 用 mise 設定に `activate_shims = false` を追加する。mise が追加する導入済みツールの bin directory は PATH に維持する。

## Consequences

- Windows の対話 PowerShell とそこから起動する子プロセスは、導入済みツールを shim でなく実体から解決する。
- shim を必要とする未導入または lazy install のツールは、`mise install` または `mise exec` で利用する。
- macOS と Linux の mise 設定は変わらない。
