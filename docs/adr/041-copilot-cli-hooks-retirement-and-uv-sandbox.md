# ADR-041: Copilot CLI フックを廃止し uv の通常実行を維持する

## Status

Accepted

## Context

配布していた Copilot CLI フックは、sandbox の導入前から操作検査や監査を担っていた。command hook の Python 起動は sandbox と衝突し、固定 interpreter、launcher、専用 runtime env の同期を要していた。フック独自の判定と監査を維持しない代わりに、これらの仕組みの保守をなくす。

uv 管理 Python を使うには、sandbox から interpreter と標準ライブラリを読み取れる必要がある。Windows の local sandbox では、uv が新規 Python を導入する際の junction 作成が拒否された。Cloud では `uv run` による必要時の Python 自動導入を使える。

[ADR-006](006-pretooluse-hook-no-allow.md) の preToolUse 判定方針を廃止し、[ADR-007](007-python-with-uv-and-pep723.md) の command hook 固定 interpreter と `uv-enforcer` による実行時強制を本 ADR で廃止する。ADR-007 の通常スクリプトの方針と [ADR-036](036-windows-uv-default-sandbox-cache.md) の uv 既定 cache 方針は維持する。

## Decision

このリポジトリが配布していた `copilot-guard`、`uv-enforcer`、`audit-log`、`audit-failure` を廃止する。git commit の専用確認、フック独自の `deny` / `ask`、監査ログ生成も廃止し、deny ルールへの移し替え、代替フック、新規実効拒否ルールは追加しない。

通常の Copilot local sandbox では、`uv python dir` が返す uv 管理 Python root を `readonlyPaths` に追加する。必要な Python は local sandbox 外であらかじめ導入する。Cloud では `uv run` による必要時の Python 自動導入を使う。

`allowDevToolAccess=true` と Copilot CLI が管理する uv 既定 cache は維持する。フック固定 Python と専用 root 解決用の runtime env は廃止する。

## Consequences

- フック独自の拒否と確認、および監査記録はなくなる。このリポジトリは同等の代替を提供しない。
- local sandbox では必要な Python が事前に導入されていない場合、読み取り専用の root への自動導入に依存できない。
- uv 管理 Python root の読み取り許可は、uv 以外の sandbox 内プロセスにも及ぶ。
