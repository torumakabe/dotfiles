# ADR-014: GitHub 多アカウント HTTPS 認証は credential の URL パス方式 + gh auth token --user で解決する

## Status

Accepted

## Context

`~/.gitconfig` は `helper = !gh auth git-credential` を使う。`gh auth git-credential` は**ホスト単位でアクティブな 1 アカウントのトークンしか返さない**（stdin の `username=` は無視。gh 2.93.0 で実機確認）。

このため EMU（Enterprise Managed Users）リポジトリ（所有者が個人と異なる、例: `<corpUser>/*`）に個人トークンが送られ、権限の無いプライベートリポジトリが **404 Not Found** になる。GitHub Copilot CLI や `gh` はプロジェクトごとに `GH_TOKEN` を注入してアカウントを上書きするため動くが、**VS Code の Git にはその注入が無い**ため破綻していた。

## Decision

`home/dot_gitconfig.tmpl` で、クローン先ディレクトリではなく HTTPS URL の所有者パスにより認証を選ぶ。

- `[credential "https://github.com"]` に `useHttpPath = true` を追加し、git が credential ブロックを所有者パスでマッチできるようにする。デフォルトヘルパーは従来どおり `helper = !gh auth git-credential`（GH_TOKEN / アクティブアカウントを尊重、アプリと個人の挙動は不変）。
- `corpUser` が設定されている場合は、対応する URL の credential helper をリセットし、`gh auth token --user <corpUser>` で取得したトークンを返す。

`gh auth token --user <account>` は **GH_TOKEN 注入下でも対象アカウントのトークンを返す**ことを実機確認済み（VS Code・アプリ端末の双方で機能）。

検討した代替案:

1. **gitdir `includeIf` で認証を出し分ける**：所有者別のディレクトリ配置を維持する必要があり、submodule と worktree も考慮しなければならないため採用しない。
2. **認証とコミット identity を同時に分離する**：identity の切り替えには別の配置規則が必要になるため対象外とする。EMU が別 identity を要求する場合に再検討する。

## Consequences

- クローン場所に依存せず所有者で認証が振り分く。VS Code・アプリ端末・CLI すべてで EMU リポジトリにアクセス可能（`git ls-remote` で実認証確認済み）。
- 前提: corp アカウントは単一（`corpUser`）。将来 EMU を複数アカウントで使うなら所有者ブロックを増やす拡張が必要。
- `useHttpPath = true` の副作用は credential キャッシュキーに path が入る程度。利用ヘルパーは stateless な gh のみなので実害なし。
- **EMU リポジトリへのコミットは個人の identity（name/email/署名鍵）のまま**。これは意図的なスコープ外。
- 既存の `gitconfig-corp` による identity の切り替えは別の機能として維持する。
- 撤回条件: 本決定は `gh auth git-credential` がアカウント指定を受け付けない現挙動への対処。将来 stdin の username を尊重して per-account トークンを返すようになったら、owner ブロックと `useHttpPath` を撤去して単一ヘルパーに戻せる。
