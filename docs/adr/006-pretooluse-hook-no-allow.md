# ADR-006: Copilot CLI preToolUse フックは allow を出力しない

## Status

Accepted

## Context

Copilot CLI の preToolUse フックは、ツール実行前に `allow` / `deny` / `ask` の判定を返せる。CLI v1.0.18 以降、1 つでも `allow` を返すと、そのツール呼び出しのユーザー承認プロンプトが完全に抑制される。

このリポジトリの `copilot-guard.py` と `uv-enforcer.py` は「特定の危険操作を止める」役割であり、安全な操作を積極的に許可する役割は持たない。にもかかわらず `allow` を返すと、本来ユーザーが承認すべき操作まで自動承認されてしまう。

## Decision

このリポジトリの preToolUse フック（`copilot-guard.py`, `uv-enforcer.py`, `node-global-enforcer.py`）は、意見がない場合に何も出力せず return する。`allow` は絶対に出力しない。`deny` / `ask` のみを使う。

## Consequences

- ユーザーの承認プロセスが意図通り維持される
- 新しいフックを追加するときも同じ規約を守る必要がある（`review-repo` でチェック）
- フック同士の判定結果の合成は Copilot CLI 側に委ねられる
