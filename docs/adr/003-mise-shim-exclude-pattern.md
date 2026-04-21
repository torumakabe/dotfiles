# ADR-003: mise shim symlink は除外パターン方式にする

## Status

Accepted

## Context

ADR-002 で mise shim を `~/.local/bin` に symlink する方針を採用したが、当初は allowlist 方式（リンクするツール名を明示列挙）だった。mise で管理するツールが増えるたびにリストを更新する必要があり、追従漏れが頻発した。

一方で、ランタイム本体（`node`, `npm`, `dotnet`, `cargo`, `rustc` 等）や一部の派生物（`cargo-*`, `rust-*`, `*.bat`, `*.ps1`, `*.sh`, `*.zst`, `*.txt`, `*-darwin-*`）はリンク不要 or 有害（環境依存の挙動になる）。

## Decision

allowlist をやめ、`run_onchange_after_21-link-mise-shims.sh.tmpl` 内で自動走査 + 2 段階の exclude を使う:

- `EXCLUDE_EXACT`: ランタイム本体など、絶対にリンクしない名前の完全一致
- `EXCLUDE_PATTERN`: ワイルドカードで弾くパターン（`cargo-*`, `*.bat` など）

これ以外は全て `~/.local/bin` にリンクする。

## Consequences

- mise で新ツールを追加しても設定変更不要
- 誤リンクは EXCLUDE の更新で対処（リストが短く済む）
- 新種のファイル（例: 新しい拡張子）が shim ディレクトリに出現した場合は EXCLUDE_PATTERN を拡張する運用になる
