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

PowerShell tool command 内で cache path を組み立てる方式では、`preToolUse` hook
適用後の path permission 判定が path 文字列を検出する。非対話起動では承認できず、
sandbox の write grant があっても tool 実行前に拒否される。補助環境変数から
`UV_CACHE_DIR` へ値だけを渡す方式では、追加の path permission なしで成功した。

## Decision

Windows の PowerShell tool command 用 uv cache を
`%USERPROFILE%\.cache\github-copilot\uv\powershell-tool` に固定し、この exact path
だけを `readwritePaths` に追加する。設定同期は user environment の
`COPILOT_DOTFILES_UV_CACHE_DIR` に同じ path を設定する。PowerShell の最終
`preToolUse` hook は path 文字列を command に含めず、この補助環境変数の値を
各 tool command の `UV_CACHE_DIR` に設定する。Copilot CLI の起動環境には
`UV_CACHE_DIR` を設定しない。

POSIX は Copilot CLI の既定 uv cache grant を利用する。command hook の pinned
Python 方式も変更しない。

## Consequences

- Windows の uv cache は `%LOCALAPPDATA%` の仮想化から分離される。
- grant と command の cache path が一致し、sandbox 内の処理だけが専用 cache を使う。
- Copilot CLI を再起動すると、user environment の補助変数を PowerShell tool が継承する。
- command に cache path を含めないため、非対話起動でも追加の path permission を要求しない。
- `%LOCALAPPDATA%\github-copilot\uv` の旧 grant は移行時に完全一致で除去する。
- ProcessContainer の仮想化仕様が変わるまで、補助環境変数、command rewrite、grant を維持する。
