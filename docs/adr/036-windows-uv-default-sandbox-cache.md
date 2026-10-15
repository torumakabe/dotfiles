# ADR-036: Windows Copilot sandbox は標準 uv cache を使う

## Status

Accepted

## Context

ADR-031 は Windows ProcessContainer の `%LOCALAPPDATA%` 仮想化を避けるため、専用 cache、環境変数、PowerShell command rewrite を導入した。Copilot CLI 1.0.99-0 と uv 0.13.0 では標準 `C:\Users\tomakabe\AppData\Local\copilot\sandbox\packages\uv` cache が実効 policy に含まれた。これら3点を除いた COPILOT_HOME 複製からローカル wheel を offline で導入し、別 tool call 2回から import できた。

## Decision

Windows も Copilot CLI が管理する uv 既定 cache を使う。uv-enforcer は Python と pip の直接実行拒否だけを担当し、cache path や PowerShell command を変更しない。設定同期は旧専用 `readwritePaths` entry と `COPILOT_DOTFILES_UV_CACHE_DIR` が `%USERPROFILE%\.cache\github-copilot\uv\powershell-tool` と完全一致する場合だけ除去する。既存 cache data、別の環境変数値、ほかの filesystem grant は保持する。

## Consequences

- Windows uv 用の追加 grant、環境変数、command rewrite は不要になる。
- 実機確認は CLI 1.0.99-0、uv 0.13.0 の PowerShell `uv run` と offline wheel 再利用に限られる。新規 PyPI download は TLS handshake failure で未確認であり、単独の `uv cache dir` や他の `uv` 呼び出しで同じ自動設定が行われるとは結論しない。
- 通常の mise shim 解決失敗は cache 適用と別の問題であり、この判断では解決しない。
- command hook は固定された uv managed Python interpreter を直接使う既存方式を維持する。
