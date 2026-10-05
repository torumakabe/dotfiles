# ADR-026: 環境別 Copilot CLI sandbox 既定値と明示設定保持

## Status

Accepted

## Context

ADR-025 は全環境で local sandbox を初回から有効にしたが、Dev Container では bubblewrap のネスト実行を保証できない。ADR-025 を本 ADR で置換する。

当初は macOS と Linux（WSL を含む）で uv 専用キャッシュを設け、ADR-031 で Windows にも展開した。しかし Copilot CLI 1.0.92-4 以降は uv の既定キャッシュへ自動的に read-write grant を与えるため、専用キャッシュ、uv-enforcer による `UV_CACHE_DIR` 書き換え、専用 `readwritePaths` は不要になった。

## Decision

### 現在有効な判断

通常の macOS、Windows、Linux、WSL では、利用者設定に `sandbox.enabled` が無い初回だけ `true` とする。Codespaces は `CODESPACES`、Dev Container は VS Code の Dev Containers 拡張が Dotfiles セットアップへ渡す `REMOTE_CONTAINERS` で判定し、未設定時は `false` とする。

既存の boolean 値は `chezmoi apply` 後も維持し、非 boolean は上書きせず拒否する。コンテナでも手動で有効化できるが、bubblewrap のネスト実行は保証しない。組織の managed settings は利用者設定より優先する。

MCP と LSP は対象外とし、`sandboxMcpServers=false` と `sandboxLspServers=false` を維持する。`allowDevToolAccess` と `allowBypass` の設定も変更しない。設定値は `home/.chezmoitemplates/copilot-user-settings.json` を管理元とする。

設定同期は管理対象外のキーと利用者所有の filesystem grant を保持する。filesystem path 配列は未設定または null の場合だけ空配列へ正規化し、配列以外は書き換え前に拒否する。旧 `version`、`allowedHosts`、`blockedHosts` は現行 policy と競合するため削除する。

uv は POSIX、Windows とも Copilot CLI の既定キャッシュ自動 grant を利用する。dotfiles は専用 `github-copilot/uv` キャッシュを作成せず、`UV_CACHE_DIR` を書き換えず、そのための `readwritePaths` も追加しない。移行時は旧専用キャッシュと完全一致する entry だけを除去し、利用者が追加した他のパスや grant は保持する。

### 撤去済みの判断

Copilot CLI 1.0.92-4 より前は、POSIX の許可済み Bash tool コマンドへ uv-enforcer が `UV_CACHE_DIR` を前置し、macOS では `~/Library/Caches/github-copilot/uv`、Linux と WSL では `${XDG_CACHE_HOME:-~/.cache}/github-copilot/uv` を使用させた。設定同期は同じ専用キャッシュを作成し、その実体パスに限定した `readwritePaths` を追加した。Windows への展開は ADR-031 で決定した。

この回避策は Copilot CLI の既定キャッシュ自動 grant により不要となり、POSIX、Windows とも撤去した。共有 `uv.toml`、CLI 起動環境全体への `UV_CACHE_DIR`、設定ファイルへの追加 readonly grant は採用しなかった。

## Consequences

- sandbox 初期値と利用者の明示設定保持は、キャッシュ回避策の撤去後も有効である。
- uv キャッシュ権限は Copilot CLI の現行仕様に依存する。将来その仕様が変わる場合は改めて判断する。
- 完全一致だけを除去するため、類似する利用者所有 entry を誤って削除しない。
- コンテナで手動有効化した場合の実行可否は dotfiles の保証外となる。
