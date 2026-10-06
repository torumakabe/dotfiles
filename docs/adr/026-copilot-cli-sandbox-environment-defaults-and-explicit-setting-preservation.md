# ADR-026: 環境別 Copilot CLI sandbox 既定値と明示設定保持

## Status

Accepted

## Context

ADR-025 は全環境で local sandbox を初回から有効にしたが、Dev Container では bubblewrap のネスト実行を保証できない。ADR-025 を本 ADR で置換する。

uv キャッシュは当初、環境別の専用パスと grant で扱った。Copilot CLI 1.0.92-4 以降、macOS、Linux、WSL では既定キャッシュへの自動 read-write grant が利用できる。一方 Windows では ProcessContainer が `%LOCALAPPDATA%` を仮想化するため、ADR-031 の専用キャッシュ判断を維持する必要がある。

## Decision

通常の macOS、Windows、Linux、WSL では、利用者設定に `sandbox.enabled` が無い初回だけ `true` とする。Codespaces は `CODESPACES`、Dev Container は VS Code の Dev Containers 拡張が Dotfiles セットアップへ渡す `REMOTE_CONTAINERS` で判定し、未設定時は `false` とする。

既存の boolean 値は `chezmoi apply` 後も維持し、非 boolean は上書きせず拒否する。コンテナでも手動で有効化できるが、bubblewrap のネスト実行は保証しない。組織の managed settings は利用者設定より優先する。

MCP と LSP は対象外とし、`sandboxMcpServers=false` と `sandboxLspServers=false` を維持する。`allowDevToolAccess` と `allowBypass` の設定も変更しない。設定値は `home/.chezmoitemplates/copilot-user-settings.json` を管理元とする。

設定同期は管理対象外のキーと利用者所有の filesystem grant を保持する。filesystem path 配列は未設定または null の場合だけ空配列へ正規化し、配列以外は書き換え前に拒否する。旧 `version`、`allowedHosts`、`blockedHosts` は現行 policy と競合するため削除する。

macOS、Linux、WSL の uv は Copilot CLI 1.0.92-4 以降の既定キャッシュ自動 grant を利用する。これらの環境では専用 `github-copilot/uv` キャッシュ、command-local `UV_CACHE_DIR` rewrite、対応する専用 `readwritePaths` を使用しない。

Windows の uv は ADR-031 に従い、`%USERPROFILE%\.cache\github-copilot\uv\powershell-tool` への exact read-write grant、同じ path を持つ `COPILOT_DOTFILES_UV_CACHE_DIR`、許可済み PowerShell tool コマンドだけに適用する command-local `UV_CACHE_DIR` rewrite を使用する。CLI 起動環境全体の `UV_CACHE_DIR` は変更しない。

Copilot CLI 1.0.92-4 より前に macOS、Linux、WSL で使用した環境別専用キャッシュと grant は撤去済みである。Windows でも一度は既定 grant へ統一したが、ProcessContainer の仮想化による不整合が判明したため、ADR-031 の Windows 専用対策を再導入した。

移行時の追加または除去は管理対象と完全一致する entry に限定し、利用者が追加した他のパスや grant は保持する。共有 `uv.toml` と設定ファイルへの追加 readonly grant は採用しない。

## Consequences

- sandbox 初期値と利用者の明示設定保持は、uv の環境別処理と独立して有効である。
- macOS、Linux、WSL の uv キャッシュ権限は Copilot CLI の現行仕様に依存する。
- Windows は補助環境変数、専用 grant、command-local rewrite の保守が必要だが、`%LOCALAPPDATA%` 仮想化と非対話の path permission 要求を回避できる。
- 完全一致だけを変更するため、類似する利用者所有 entry を誤って削除しない。
- コンテナで手動有効化した場合の実行可否は dotfiles の保証外となる。
