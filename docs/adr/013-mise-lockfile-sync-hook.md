# ADR-013: mise lockfile 変更時に install と実行パスを同期する

## Status

Accepted

## Context

`~/.config/mise/mise.lock` が更新されても、ローカルの install、shim、実行パスは
自動では更新されない。Windows の非対話プロセスで mise shim を User PATH に置くと、
shim の解決や auto-install に依存し、lockfile と実体の不整合が起きやすい。

`private_mise.lock` は chezmoi が管理するため、lockfile を適用した直後に install と
実行パスを同期すれば、非対話プロセスも導入済みの実体を直接実行できる。

## Decision

`run_onchange_after_15-mise-sync-tools` は lockfile の hash 変更時に `mise install` と
`mise reshim` を実行する。Windows では両方の成功後に `mise bin-paths` が返す実体の
directory を User PATH の先頭へ同期し、mise shim directory は永続 PATH に置かない。

同期処理は前回管理した実体 directory を state file に記録する。次回は、その記録と
旧 mise shim directory だけを除去してから現在の実体 directory を追加し、利用者が
管理する他の PATH entry は保持する。install、reshim、bin path の検証に失敗した場合は
PATH と state file を更新せず、`chezmoi apply` を失敗させる。

## Consequences

- lockfile、install marker、shim、Windows の非対話プロセス用 PATH が一括で更新される。
- Windows の非対話プロセスは shim や auto-install を介さず導入済み実体を実行する。
- tool の追加、削除、version 変更で不要になった管理対象 directory を除去できる。
- lockfile 変更時は install と PATH 同期の時間が `chezmoi apply` に加わる。
- command hook の pinned Python 方式はこの PATH に依存せず、従来どおり維持する。
- Windows の実体 directory 同期は Copilot sandbox の shim 解決失敗に対する暫定措置であり、
  ProcessContainer 内で shim が config、lockfile、state を解決できるようになったら撤去する。
  判断には、非対話 PowerShell tool から `jq`、`rg`、`uv` を追加許可なしで起動できることの
  実機確認を要する。撤去時の清掃手順は [`docs/operations.md`](../operations.md) に置く。
