# ADR-036: Windows Copilot sandbox は標準 uv cache を使う

## Status

Accepted

## Context

ADR-031 で導入した専用 cache、環境変数、PowerShell command rewrite は不要になったため、
Windows も Copilot CLI が管理する uv の既定 cache を使う。

## Decision

Windows も Copilot CLI が管理する uv 既定 cache を使う。uv-enforcer は Python と pip の直接実行拒否だけを担当し、cache path や PowerShell command を変更しない。設定同期は旧専用 `readwritePaths` entry と `COPILOT_DOTFILES_UV_CACHE_DIR` が `%USERPROFILE%\.cache\github-copilot\uv\powershell-tool` と完全一致する場合だけ除去する。既存 cache data、別の環境変数値、ほかの filesystem grant は保持する。

## Consequences

- Windows uv 用の追加 grant、環境変数、command rewrite は不要になる。
- mise shim の解決は cache の書き込み許可とは別の問題として扱う。
- command hook は固定された uv managed Python interpreter を直接使う既存方式を維持する。
