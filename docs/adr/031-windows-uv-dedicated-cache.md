# ADR-031: Windows Copilot sandbox の uv cache を非仮想化パスへ分離する

## Status

Accepted

## Context

Copilot CLI 1.0.92-4 の Windows ProcessContainer は `%LOCALAPPDATA%` を
`Packages\sandbox.{GUID}\AC` 配下へ仮想化する。このため、ホストの
`%LOCALAPPDATA%\uv\cache` に対する write grant は sandbox 内の uv cache に効かない。

以前採用した `%LOCALAPPDATA%\github-copilot\uv` も同じ仮想化の対象であり、
専用 cache として不適切だった。実機検証では、`%USERPROFILE%` 配下の exact path への
write grant と PowerShell tool command 内だけの `UV_CACHE_DIR` 設定により、
`uv run`、managed Python、marker の永続化が成功した。

## Decision

Windows の PowerShell tool command 用 uv cache を
`%USERPROFILE%\.cache\github-copilot\uv\powershell-tool` に固定し、この exact path
だけを `readwritePaths` に追加する。PowerShell の最終 `preToolUse` hook は
`$env:USERPROFILE` から同じ path を構築し、各 tool command にだけ
`UV_CACHE_DIR` を設定する。Copilot CLI の起動環境には設定しない。

POSIX は Copilot CLI の既定 uv cache grant を利用する。command hook の pinned
Python 方式も変更しない。

## Consequences

- Windows の uv cache は `%LOCALAPPDATA%` の仮想化から分離される。
- grant と command の cache path が一致し、sandbox 内の処理だけが専用 cache を使う。
- `%LOCALAPPDATA%\github-copilot\uv` の旧 grant は移行時に完全一致で除去する。
- ProcessContainer の仮想化仕様が変わるまで Windows 固有の回避策を維持する。
