# ADR-036: Windows Copilot sandbox は標準 uv cache を使う

## Status

Accepted

## Context

ADR-031 で導入した専用 cache、環境変数、PowerShell command rewrite は不要になったため、
Windows も Copilot CLI が管理する uv の既定 cache を使う。

当時の `uv-enforcer` は Python と pip の直接実行を拒否し、command hook は固定した uv managed Python interpreter を使っていた。これらのフックに関する仕組みは [ADR-041](041-copilot-cli-hooks-retirement-and-uv-sandbox.md) で廃止した。

## Decision

Windows も Copilot CLI が管理する uv 既定 cache を使う。旧専用 cache からの移行は完了し、設定同期に移行用の削除処理を残さない。旧専用 cache に関する既存の data、環境変数、filesystem grant は保持する。

## Consequences

- Windows の uv 既定 cache 用の専用 grant、環境変数、command rewrite は不要になる。
- mise shim の解決は cache の書き込み許可とは別の問題として扱う。
- uv 管理 Python root の読み取り許可は ADR-041 で扱う。
