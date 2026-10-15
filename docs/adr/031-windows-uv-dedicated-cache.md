# ADR-031: Windows Copilot sandbox の uv cache を非仮想化パスへ分離する

## Status

Superseded by ADR-036

## Context

Windows sandbox では `%LOCALAPPDATA%` の仮想化により、ホスト側の cache path に対する
許可が sandbox 内の uv に適用されない場合がある。そのため、以前は専用 cache と
PowerShell command 内の設定を使っていた。

## Decision

Windows の PowerShell tool 用 cache を
`%USERPROFILE%\.cache\github-copilot\uv\powershell-tool` に固定し、この path だけを
`readwritePaths` に追加する。設定同期は `COPILOT_DOTFILES_UV_CACHE_DIR` を設定し、
PowerShell tool command の `UV_CACHE_DIR` にその値を渡す。Copilot CLI の起動環境には
`UV_CACHE_DIR` を設定しない。

POSIX は Copilot CLI の既定 uv cache grant を利用する。command hook の pinned
Python 方式も変更しない。

## Consequences

- Windows の sandbox 内の uv は、専用 cache を使う。
- `%LOCALAPPDATA%\github-copilot\uv` の旧 grant は移行時に完全一致で除去する。
- この判断は [ADR-036](036-windows-uv-default-sandbox-cache.md) により置き換えられた。
  旧 grant と環境変数の移行時の清掃手順は [`docs/operations.md`](../operations.md) に記載する。
