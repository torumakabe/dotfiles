# ADR-014: GitHub 多アカウント HTTPS 認証は credential の URL パス方式 + gh auth token --user で解決する

## Status

Accepted

## Context

`~/.gitconfig` は `helper = !gh auth git-credential` を使う。`gh auth git-credential` は**ホスト単位でアクティブな 1 アカウントのトークンしか返さない**（stdin の `username=` は無視。gh 2.93.0 で実機確認）。

このため EMU（Enterprise Managed Users）リポジトリ（所有者が個人と異なる、例: `<corpUser>/*`）に個人トークンが送られ、権限の無いプライベートリポジトリが **404 Not Found** になる。Copilot CLI や `gh` はプロジェクトごとに `GH_TOKEN` を注入してアカウントを上書きするため動くが、**VS Code の Git にはその注入が無い**ため破綻していた。

## Decision

`home/dot_gitconfig.tmpl` の credential セクションを認証のみ変更（11 行追加）:

- `[credential "https://github.com"]` に `useHttpPath = true` を追加し、git が credential ブロックを所有者パスでマッチできるようにする。デフォルトヘルパーは従来どおり `helper = !gh auth git-credential`（GH_TOKEN / アクティブアカウントを尊重、アプリと個人の挙動は不変）。
- corp 所有者専用ブロックを `{{ if .corpUser }}` ガードで追加。`[credential "https://github.com/<corpUser>"]` で空 `helper =` リセット後、`helper = "!f() { test \"$1\" = get && echo username=<corpUser> && echo password=$(gh auth token --user <corpUser>); }; f"`。

`gh auth token --user <account>` は **GH_TOKEN 注入下でも対象アカウントのトークンを返す**ことを実機確認済み（VS Code・アプリ端末の双方で機能）。

検討した代替案:

1. **gitdir `includeIf` で認証を出し分ける** — 却下。所有者別ディレクトリ運用の規律が必要（過去に放置）、`ghq.root` のチキンエッグ、submodule/worktree がパス判定から外れ EMU で 404 という事故を招く（当リポジトリは worktree 運用でリスク大）。
2. **認証 + identity を両方分離（gitdir 併用）** — 見送り。identity は URL/リモート単位で出し分け不可で `includeIf gitdir:` 依存となり上記の規律・副作用が戻る。署名鍵分離は `allowed_signers` の両鍵登録が必要で ADR-012 の op-ssh-sign wrapper とも干渉しうる。EMU が別 identity を要求したら再検討する。

## Consequences

- クローン場所に依存せず所有者で認証が振り分く。VS Code・アプリ端末・CLI すべてで EMU リポジトリにアクセス可能（`git ls-remote` で実認証確認済み）。
- 前提: corp アカウントは単一（`corpUser`）。将来 EMU を複数アカウントで使うなら所有者ブロックを増やす拡張が必要。
- `useHttpPath = true` の副作用は credential キャッシュキーに path が入る程度。利用ヘルパーは stateless な gh のみなので実害なし。
- **EMU リポジトリへのコミットは個人の identity（name/email/署名鍵）のまま**。これは意図的なスコープ外。
- 既存の `~/workspace_corp` / `gitconfig-corp`（gitdir includeIf）機構は本問題には未使用（リポジトリをそこに置いていないため発火しない）。identity 分離など別目的として据え置く。
- 撤回条件: 本決定は `gh auth git-credential` がアカウント指定を受け付けない現挙動への対処。将来 stdin の username を尊重して per-account トークンを返すようになったら、owner ブロックと `useHttpPath` を撤去して単一ヘルパーに戻せる。
