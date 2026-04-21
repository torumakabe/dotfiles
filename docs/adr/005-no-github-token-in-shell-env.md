# ADR-005: GITHUB_TOKEN を環境変数に常駐させない

## Status

Accepted

## Context

`~/.zshrc` 等で `GITHUB_TOKEN` をエクスポートしておくと、gh CLI や各種スクリプトが自動認証できて便利である一方、同じシェルから起動する AI エージェント（Copilot CLI、Claude Code 等）にもトークンが露出する。エージェントが意図せずトークンを他プロセスに渡したり、ログに記録する事故リスクがある。

## Decision

`GITHUB_TOKEN` をシェル設定（`.zshrc`, `.profile` 等）に常駐させない。必要な時だけ手動で `export` するか、`gh auth` の認証情報を利用する。

## Consequences

- エージェントへの機密情報露出リスクを低減
- 一部のスクリプトは明示的に token を取得する必要がある（`gh auth token` 等）
- GitHub Actions など CI 環境では別途トークンを渡す必要があるが、そこでは元々ローカル設定は無関係
