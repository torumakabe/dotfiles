# ADR-041: GitHub Copilot フックを廃止する

## Status

Accepted

## Context

このリポジトリは、GitHub Copilot CLI の sandbox 導入前から、操作の拒否と確認、および実行記録のために4つのフックを配布していた。

GitHub Copilot CLI は sandbox とツール実行の権限確認を提供する。一方、sandbox 内でフックを実行する際の衝突を避けるため、固定 Python と読み取り許可などの個別対応を保守していた。

## Decision

`copilot-guard`、`uv-enforcer`、`audit-log`、`audit-failure` を廃止する。フック独自の判定と記録のために実行環境を維持せず、別の実装による代替フックも作らない。

旧フックの規則を `deniedPaths` へ移さず、`allowDevToolAccess=true` は維持する。

## Consequences

- フックによるパス単位の拒否と確認、`git commit` の確認、`python` と `pip` の直接実行の拒否、監査ログはなくなる。sandbox と権限確認はこれらを同等に置き換えるものではない。
- 既存端末から配布済みフックを削除する。対象と扱いは[移行手順](../operations.md#github-copilot-フック廃止時の移行)に記載する。
- [ADR-006](006-pretooluse-hook-no-allow.md) の preToolUse 判定方針と、[ADR-007](007-python-with-uv-and-pep723.md) のフック用固定 interpreter と実行時強制を廃止する。通常のスクリプトに関する ADR-007 の方針は維持する。
- sandbox 内での uv 管理 Python の扱いは [ADR-042](042-uv-managed-python-readonly-grant.md) で定める。
