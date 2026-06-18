# ADR-015: Copilot CLI shell のネットワーク制御は local sandbox で行う

## Status

Accepted

## Context

ADR-010 では preToolUse Hook による URL allowlist を採用した。Copilot CLI の設定 schema で local sandbox が確認でき、shell command の外向きネットワーク制御を CLI 側に移せる。対象は shell command の network control のみで、MCP / LSP / filesystem sandboxing は別判断とする。

## Decision

Copilot CLI の shell command network control は local sandbox に移行する。`sandbox.enabled=true`、`userPolicy.network.allowOutbound=false`、`allowLocalNetwork=true` を基本とし、必要な例外は `allowedHosts` / `blockedHosts` で表現する。MCP / LSP / filesystem は sandbox 対象外として `sandboxMcpServers=false`、`sandboxLspServers=false`、`addCurrentWorkingDirectory=false`、`userPolicy.filesystem` は empty / preserved arrays、`clearPolicyOnExit=false` を維持する。sandbox disabled 時の Hook fallback は持たない。

## Consequences

- ADR-010 の URL allowlist Hook 方針を置き換える
- ネットワーク遮断は URL 文字列検査ではなく sandbox policy に委ねる
- MCP / LSP / filesystem の隔離は本 ADR では保証しない
- `allowLocalNetwork=true` のため localhost / link-local は許可する。必要なら metadata endpoint 等を `blockedHosts` に追加する
- sandbox を無効化した運用では shell network 制御も無効になる
