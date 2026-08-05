# ADR-024: gh-stack skill と extension は公式 CLI で導入する

## Status

Accepted

## Context

Copilot が Stacked PR を設計して操作するには、判断とコマンドを教える skill と、`gh stack` コマンドを提供する GitHub CLI extension が必要になる。GitHub CLI は `gh extension install` に加えて `gh skill install` を提供しており、skill の取得元と更新状態を管理できる。公式 skill をリポジトリへ複製すると、上流とローカルコピーの同期作業が重複する。

## Decision

`gh-stack` skill は `gh skill install github/gh-stack gh-stack --agent github-copilot --scope user` で公式リポジトリから取得する。GitHub CLI extension は `gh extension install github/gh-stack` で取得する。chezmoi のセットアップスクリプトは、各要素が未導入の場合だけコマンドを実行し、導入済みの版を自動更新しない。

skill と extension の版は固定しない。新規端末が過去の版へ固定されることを避け、公式コマンドが解決する最新安定版を取得する。端末間の版差を許容し、更新候補は定期レビューで検出する。

Stacked PR を提案する条件は `copilot-instructions.md` で管理し、`gh stack` の操作方法は公式 skill を正本とする。更新候補は `gh skill update gh-stack --dry-run` と `gh extension upgrade gh-stack --dry-run` で確認し、更新は明示的に実行する。

## Consequences

リポジトリは公式 skill のコピーと上流 commit を管理しない。日常の apply は意図しない更新を行わない一方、端末を構築または明示的に更新した時期によって skill と extension の版が異なり得る。初回導入と更新には GitHub への接続が必要である。
