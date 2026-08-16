# ADR-015: Copilot CLI shell のネットワーク制御は local sandbox で行う

## Status

Superseded by ADR-026

[ADR-026](026-copilot-cli-sandbox-environment-defaults-and-explicit-setting-preservation.md) により、shell command の network control だけを対象とする方針から、環境別の初回値と利用者の明示設定を user-level settings で管理する方針へ移行した。MCP と LSP を sandbox の対象外とする判断も ADR-026 が引き継ぐ。

## Context

ADR-010 では preToolUse Hook による URL allowlist を採用した。しかし、Hook の fail-open、Hook が発火しない経路、コマンド名や URL 文字列検査の抜け道により、shell network control の境界としては維持しない。Copilot CLI の設定 schema で local sandbox が確認でき、shell command の外向きネットワーク制御を CLI 側に移せる見込みがある。対象は shell command の network control のみで、MCP / LSP / filesystem sandboxing は別判断とする。

## Decision

Copilot CLI の shell command network control は local sandbox に移行する。現時点では sandbox を有効にするが、外向き通信を遮断せず、host rule も設定しない。MCP と LSP は sandbox の対象に含めず、sandbox が無効な場合の Hook fallback も持たない。POSIX と PowerShell の実装は既存の `readwritePaths`、`readonlyPaths`、`deniedPaths` を保持するが、新しい filesystem 制限は定義せず、filesystem isolation は保証範囲外とする。投入する設定値は `home/run_onchange_after_35-configure-copilot-sandbox.{sh,ps1}.tmpl` を正本とし、local sandbox が成熟した段階で遮断対象を見直す。

## Tracking

- GitHub Copilot CLI の local sandbox の現状と改善状況は [github/copilot-cli#3861](https://github.com/github/copilot-cli/issues/3861) で追跡する。

## Consequences

- ADR-010 の URL allowlist Hook 方針を置き換える
- ネットワーク遮断は URL 文字列検査ではなく sandbox policy に委ねるが、現時点では遮断設定を投入しない
- URL allowlist Hook とネットワーク系 `--deny-tool` 補助列挙は、抜け道により形骸化しやすいため復活させない
- MCP / LSP / filesystem の隔離は本 ADR では保証しない
- 旧設定の残留で外向き通信が遮断されないよう、管理対象の host rule は空にする
- shell network control は sandbox policy に集約するため、Hook や `--deny-tool` による fallback は持たない
