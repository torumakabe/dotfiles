# ADR-003: mise shim symlink は除外パターン方式にする

## Status

Deprecated

## Context

mise shim のリンク生成を撤去し、除外パターンも不要になったため、本 ADR を廃止した。現在の導入方針は [ADR-028](028-remove-mise-use-official-per-tool-install-paths.md) を参照。以下は採用当時の記録であり、現在の操作手順ではない。

ADR-002 で mise shim を `~/.local/bin` に symlink する方針を採用したが、当初は allowlist 方式（リンクするツール名を明示列挙）だった。mise で管理するツールが増えるたびにリストを更新する必要があり、追従漏れが頻発した。

一方で、言語ランタイム本体を `~/.local/bin` へリンクすると、同ディレクトリを優先するアプリケーションが意図しない版を使うおそれがある。実行可能な補助ファイルもリンク対象ではない。Rust は ADR-016 により mise の管理外であり、`cargo` や `rustc` の shim は生成されない。

## Decision

allowlist をやめ、`run_onchange_after_21-link-mise-shims.sh.tmpl` 内で自動走査 + 2 段階の exclude を使う:

- `EXCLUDE_EXACT`: ランタイム本体など、リンクしない名前の完全一致
- `EXCLUDE_PATTERN`: 実行可能な補助ファイルを除くワイルドカード

具体的な除外対象は、同スクリプトの `EXCLUDE_EXACT` と `EXCLUDE_PATTERN` を正本とする。

これ以外は全て `~/.local/bin` にリンクする。

## Consequences

- mise で新ツールを追加しても設定変更不要
- 誤リンクは EXCLUDE の更新で対処（リストが短く済む）
- 新種のファイル（例: 新しい拡張子）が shim ディレクトリに出現した場合は EXCLUDE_PATTERN を拡張する運用になる
