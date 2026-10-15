# ADR-035: Copilot CLI MCP servers を sandbox 対象にする

## Status

Accepted

## Context

ADR-026 は MCP sandbox を無効のままにしていたため、MCP の判断だけを本 ADR で置き換える。Copilot CLI 1.0.98-0 で隔離設定を使い、Guard を有効にして両条件で同じ repository source を指定し、合成 `SANDBOX_PROBE` で local stdio MCP を比較した。両条件で `allowBypass=false` とし、initialize/tool call は成功、Guard hook は各 1 回だった。sandbox 無効時は `ORIGINAL`、有効時は `copilot_mask_<32 hex>` の `PLACEHOLDER` を観測した。実際の 4 credentials 値は測定していないため、それらの秘匿を実証するものではない。

## Decision

`sandboxMcpServers=true` とする。local MCP process は `sandbox.enabled=true` の session で sandbox 内に実行する。`sandboxLspServers=false` を含む他の dotfiles 設定は変更しない。ADR-026 の環境別 `sandbox.enabled` 初回値と明示設定保持の判断も維持する。

## Consequences

- MCP server の sandbox を有効化し、合成 probe では元の値でなく placeholder が観測された。
- 実際の credentials の保護は未検証であり、この測定結果から保証しない。
