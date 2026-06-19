# ADR-015: Copilot CLI shell のネットワーク制御は local sandbox で行う

## Status

Accepted

## Context

ADR-010 では preToolUse Hook による URL allowlist を採用した。しかし、Hook の fail-open、Hook が発火しない経路、コマンド名や URL 文字列検査の抜け道により、shell network control の境界としては維持しない。Copilot CLI の設定 schema で local sandbox が確認でき、shell command の外向きネットワーク制御を CLI 側に移せる見込みがある。対象は shell command の network control のみで、MCP / LSP / filesystem sandboxing は別判断とする。

## Decision

Copilot CLI の shell command network control は local sandbox に移行する。ただし、現時点では sandbox を有効化するだけにとどめ、外向き通信の遮断や host rule は設定しない。`sandbox.enabled=true`、`userPolicy.network.allowOutbound=true`、`allowLocalNetwork=true`、`allowedHosts=[]`、`blockedHosts=[]` を基本とし、local sandbox が成熟した段階で遮断対象を増やす。MCP / LSP / filesystem は sandbox 対象外として `sandboxMcpServers=false`、`sandboxLspServers=false`、`addCurrentWorkingDirectory=false`、`userPolicy.filesystem` は empty / preserved arrays、`clearPolicyOnExit=false` を維持する。sandbox disabled 時の Hook fallback は持たない。

## Tracking

- GitHub Copilot CLI の local sandbox の現状と改善状況は [github/copilot-cli#3861](https://github.com/github/copilot-cli/issues/3861) で追跡する。

## Consequences

- ADR-010 の URL allowlist Hook 方針を置き換える
- ネットワーク遮断は URL 文字列検査ではなく sandbox policy に委ねるが、現時点では遮断設定を投入しない
- URL allowlist Hook とネットワーク系 `--deny-tool` 補助列挙は、抜け道により形骸化しやすいため復活させない
- MCP / LSP / filesystem の隔離は本 ADR では保証しない
- 旧設定の残留で外向き通信が遮断されないよう、管理対象の host rule は空にする
- shell network control は sandbox policy に集約するため、Hook や `--deny-tool` による fallback は持たない
