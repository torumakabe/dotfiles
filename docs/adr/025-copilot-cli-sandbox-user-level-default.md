# ADR-025: Copilot CLI local sandbox は user-level settings で既定有効にする

## Status

Superseded by ADR-026

## Context

ADR-015 は Copilot CLI の shell command に対するネットワーク制御を local sandbox へ移したが、対象は shell command の network control に限り、MCP、LSP、filesystem isolation は対象外としていた。local sandbox は filesystem paths や auth、network の設定も持つため、これらを chezmoi 管理下の cross-platform な既定値として揃える必要がある。一方で、file-based の managed settings による強制は、利用者が個別コマンドの不具合を回避する手段を塞ぎ、Copilot CLI の preview 版で sandbox 自体に不具合が出た場合の復旧手段を持たない。ADR-015 を本 ADR で置換し、対象を shell command の network control から cross-platform の shell/filesystem sandbox 既定値へ広げる。

## Decision

`home/.chezmoitemplates/copilot-user-settings.json` を正本とし、Windows、macOS、ネイティブ Linux、WSL2、Codespaces、Dev Container の user-level `~/.copilot/settings.json` へ `sandbox.enabled=true` を既定値として配布する。`experimental=true` とし、`addCurrentWorkingDirectory=true`、`allowDevToolAccess=true`、`auth.git=true`、`auth.gh=true`、`network.allowOutbound=true`、`network.allowLocalNetwork=true` を設定する。既存の filesystem path rules（`readwritePaths`、`readonlyPaths`、`deniedPaths`）は維持し、stale な network 系キーは chezmoi apply のたびに除去する。MCP と LSP は `sandboxMcpServers=false` と `sandboxLspServers=false` により sandbox の対象外に据え置く。

利用者は Copilot CLI 組み込みの `/sandbox disable` で `sandbox.enabled=false` を持続化できる。`home/run_onchange_after_35-configure-copilot-sandbox.{sh,ps1}.tmpl` は desired template を適用する前に既存の `sandbox.enabled` を検査し、値が boolean であれば他の repo-managed な sandbox key をマージした後にその値を復元する。既存の key が欠落していれば true を採用し、null や非 boolean であれば黙って上書きせず chezmoi apply を明示的なエラーで止める。この復元により、`/sandbox disable` の効果は `/sandbox enable` を実行するまで、将来の chezmoi apply や template 更新を跨いで残る。

`copilot-guardrails --allow-all` を維持し、ツール権限の個別承認を省略する。個々のコマンドが sandbox の制約に抵触する場合は、system が承認する bypass（`allowBypass=true` による sandbox 外の再実行）を優先する。`/sandbox disable` は preview 版の sandbox 自体に不具合が出た場合の緊急手段と位置付け、個別コマンドの回避には用いない。

Windows のパッケージ導入は引き続き WinGet Configuration が担い、GitHub Copilot CLI も対象とする。WinGet DSC は設定ファイルの配布を行わず、パッケージ導入に限定する。組織が enterprise の managed-settings.json で sandbox を強制する場合、`/sandbox` コマンドの UI は managed もしくは locked と表示され、利用者はローカルで無効化できない。この管理は本リポジトリの対象外とする。

backend は macOS で Seatbelt、Linux、WSL2、Codespaces、Dev Container で bubblewrap、Windows で ProcessContainer とする。Linux では bubblewrap 0.5.0 以降を apt で導入し、user namespace や bwrap の probe に失敗した場合は warning に留め、sandbox の既定有効化自体は維持する。

## Consequences

- `sandbox.enabled` の既定対象が shell command の network control から、6 環境の Copilot CLI local sandbox 全体へ広がる
- 強制は user-level settings のみで行い、file-based managed settings による enforcement は本リポジトリでは提供しない
- `/sandbox disable` で持続化した `false` は、型検査を伴う復元ロジックにより将来の chezmoi apply を跨いで維持される
- backend が環境ごとに異なるため保証内容は一致しない。Windows は `deniedPaths` に対応せず、Linux と macOS の proxy は cooperative であるため、環境差の周知が必要になる
- MCP と LSP の隔離は保証しない。保証する場合は改めて ADR を作成する
- allowedHosts/blockedHosts は Copilot CLI v1.0.69 で削除済みのため、host rule によるネットワーク制御には依存しない
- Linux では bwrap probe 失敗時の warning-only 運用が残るため、bubblewrap の前提条件（user namespace 有効化）からの逸脱を継続的に監視する必要がある
