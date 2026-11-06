# ADR-006: Copilot CLI preToolUse フックは allow を出力しない

## Status

Deprecated

## Context

Copilot CLI の preToolUse フックは、ツール実行前に `allow` / `deny` / `ask` の判定を返せる。CLI v1.0.18 以降、1 つでも `allow` を返すと、そのツール呼び出しのユーザー承認プロンプトが完全に抑制される。

当時の `copilot-guard.py` と `uv-enforcer.py` は特定の危険操作を止める役割であり、安全な操作を積極的に許可する役割は持たなかった。にもかかわらず `allow` を返すと、本来ユーザーが承認すべき操作まで自動承認されてしまう。

[ADR-041](041-copilot-cli-hooks-retirement-and-uv-sandbox.md) により両フックの配布とフック独自の `deny` / `ask` を廃止した。後継のフック判定は設けないため、本判断も廃止する。

## Decision

廃止前の preToolUse フック（`copilot-guard.py`、`uv-enforcer.py`）は、意見がない場合に何も出力せず return した。`allow` は出力せず、`deny` / `ask` のみを使った。

## Consequences

- ユーザーの承認プロセスを意図どおり維持することを狙った
- 当時は新しいフックを追加するときも同じ規約を守る必要があった（`review-repo` でチェック）
- フック同士の判定結果の合成は Copilot CLI 側に委ねていた
