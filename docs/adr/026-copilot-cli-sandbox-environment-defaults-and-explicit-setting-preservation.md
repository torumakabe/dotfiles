# ADR-026: 環境別 Copilot CLI sandbox 初回既定値と明示設定保持

## Status

Accepted

## Context

ADR-025 は全環境で local sandbox を初回から有効にした。しかし実機の Dev Container では bubblewrap の user namespace probe と Copilot CLI の shell command が失敗し、個別 bypass も提示されなかった。GitHub Copilot CLI の公式文書は Linux ホストを説明するが、コンテナ内での bubblewrap のネスト実行を保証しない。変化しやすい版と詳細ログは ADR に固定せず、[`docs/copilot-sandbox-verification.md`](../copilot-sandbox-verification.md) を検証記録とする。ADR-025 を本 ADR で置換する。

## Decision

通常の macOS、Windows、Linux、WSL では、利用者設定に `sandbox.enabled` が無い初回だけ `true` とする。Codespaces は `CODESPACES`、Dev Container は VS Code の Dev Containers 拡張が Dotfiles セットアップへ渡す `REMOTE_CONTAINERS` で判定し、未設定時は `false` とする。

全環境で、既存値が boolean の `true` または `false` なら `chezmoi apply` 後も維持し、非 boolean は上書きせずエラーとして拒否する。コンテナでも利用者は手動で有効化できるが、bubblewrap のネスト実行は公式サポートを確認できない限り成功を保証しない。組織の managed settings は利用者設定より優先する。

MCP と LSP を local sandbox の対象外とする ADR-025 の判断も継承し、`sandboxMcpServers=false` と `sandboxLspServers=false` を維持する。設定値の実装は `home/.chezmoitemplates/copilot-user-settings.json` を正本とする。

設定同期は、リポジトリが管理する sandbox policy だけを更新し、管理対象外のキーを階層にかかわらず保持する。filesystem の `readwritePaths`、`readonlyPaths`、`deniedPaths` は、未設定または null の場合だけ空配列へ正規化し、既存の配列を維持する。配列以外の値は意図を推測して変換せず、設定ファイルを書き換える前にエラーとして拒否する。

`sandbox.userPolicy.version` は、ADR-015 が採用した Windows AppContainer schema の版を示すためにリポジトリが追加していた値であり、現在のクロスプラットフォームポリシーの利用者設定ではないため削除する。旧ネットワーク制御の `allowedHosts` と `blockedHosts` も、現行の outbound network policy と競合する残存キーとして削除する。

## Consequences

- Codespaces と Dev Container の初回値は、各環境が Dotfiles セットアップへ渡す既存の環境変数によって通常環境と分岐する
- 初回無効のコンテナでは、利用不能な backend に対する bubblewrap 診断を抑止する
- 設定同期の検証契約は、環境別初回値、既存 boolean の保持、非 boolean の拒否、filesystem path の型検査、管理対象外キーの保持、手動有効化後の保持を対象とする
- コンテナで手動有効化した場合の実行可否は container runtime と user namespace に依存し、dotfiles の保証外となる
- npm の導入方法や `.devcontainer/devcontainer-lock.json` はこの判断の対象外とする
