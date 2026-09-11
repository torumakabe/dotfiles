# ADR-026: 環境別 Copilot CLI sandbox 既定値と uv コマンド専用キャッシュ

## Status

Accepted

## Context

ADR-025 は全環境で local sandbox を初回から有効にしたが、Dev Container では bubblewrap のネスト実行を保証できない。macOS と Linux（WSL を含む）では、ホストの uv 設定と通常のキャッシュを変更せずに sandbox 内の uv を動かすため、対象コマンドだけに専用キャッシュを選択させ、限定した書き込み権限と一致させる。Windows は現在の環境で動作するという利用者報告だけを根拠として変更しない。自動的な RW 付与を根拠にはしない。ADR-025 を本 ADR で置換する。

共有 `uv.toml` によるキャッシュ移設案は実環境へ適用する前に取り下げた。仮の `HOME` と `uv.toml` を使った結果は探索的な検証であり、今回選択した実装の受け入れ根拠にはしない。通常の `HOME`、Python の自動選択、登録した実際の hook を使い、検証専用の Python RO を追加しない実 CLI 検証では、RW なしで書き込みが拒否され、RW ありでホストへマーカーが永続化した。詳細は[検証記録](../copilot-sandbox-verification.md)で扱う。

## Decision

通常の macOS、Windows、Linux、WSL では、利用者設定に `sandbox.enabled` が無い初回だけ `true` とする。Codespaces は `CODESPACES`、Dev Container は VS Code の Dev Containers 拡張が Dotfiles セットアップへ渡す `REMOTE_CONTAINERS` で判定し、未設定時は `false` とする。

既存の boolean 値は `chezmoi apply` 後も維持し、非 boolean は上書きせず拒否する。コンテナでも手動で有効化できるが、bubblewrap のネスト実行は保証しない。組織の managed settings は利用者設定より優先する。

MCP と LSP は対象外とし、`sandboxMcpServers=false` と `sandboxLspServers=false` を維持する。uv 対応のために sandbox を無効化せず、`allowDevToolAccess` と `allowBypass` の設定も変更しない。実 CLI の受け入れ検証では bypass を無効にする。設定値は `home/.chezmoitemplates/copilot-user-settings.json` を管理元とする。

設定同期は管理対象外のキーと利用者所有の filesystem grant を保持する。filesystem path 配列は未設定または null の場合だけ空配列へ正規化し、配列以外は書き換え前に拒否する。旧 `version`、`allowedHosts`、`blockedHosts` は現行 policy と競合するため削除する。

- POSIX の uv-enforcer は既存の拒否判定をすべて済ませた後、許可された Bash ツールの引数に限り、コマンド単位の `UV_CACHE_DIR` 指定を加える。専用キャッシュは macOS で `~/Library/Caches/github-copilot/uv`、Linux と WSL で `${XDG_CACHE_HOME:-~/.cache}/github-copilot/uv` とする。CLI 起動環境には `UV_CACHE_DIR` を設定しない。
- POSIX の設定同期は専用キャッシュを作成し、その実体パスに限定した `readwritePaths`（RW）を確保する。既存の利用者規則の readonly、denied、順序を保持し、安全でないパスや競合は規則を緩めず拒否する。所有権の別状態ファイル、ジャーナル、旧規則の自動撤去は導入しない。
- ホストの `uv.toml` と通常の uv キャッシュは変更せず、設定ファイルへの追加 RO も与えない。Windows にはコマンドの書き換えも grant の追加も行わない。
- 回避策の適用範囲と撤去条件は[リポジトリの共通指示](../../.github/copilot-instructions.md#ワークアラウンド定期チェック対象)に集約する。

## Consequences

- コマンド単位の指定により、通常のホスト uv の設定とキャッシュを維持し、設定ファイル全体を追加で読み取り可能にせずに済む。一方、専用キャッシュとの重複でディスク使用量が増え、同じ専用キャッシュを使う後続コマンドへのキャッシュ汚染は防げない。
- キャッシュ選択は uv-enforcer が書き換える対象コマンドに限られ、CLI の全子プロセスには及ばない。既存規則と競合する場合の停止と、不要になった規則の手動整理を受け入れる。
- Windows の動作機構は未検証であり、利用者報告を他の Windows 環境での書き込み保証へ一般化しない。
- コンテナで手動有効化した場合の実行可否は dotfiles の保証外となる。
