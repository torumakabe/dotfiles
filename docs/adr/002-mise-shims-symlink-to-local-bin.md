# ADR-002: mise shim を ~/.local/bin に symlink する

## Status

Accepted

## Context

GitHub Desktop に組み込まれた Copilot CLI SDK は子シェルを `bash --norc --noprofile` で起動し、独自の hardcoded PATH を使う。そこには `~/.local/bin` は含まれるが `~/.local/share/mise/shims` は含まれない。結果として、mise で管理しているツール（`uv`, `gh`, `copilot` 以外のランタイム等）がエージェント実行環境から見えなくなる。

`~/.profile` の source も行われないため、PATH 修正では解決できない。

## Decision

chezmoi の `run_onchange_after_21-link-mise-shims.sh.tmpl` で、mise shims ディレクトリ内のバイナリを `~/.local/bin` に symlink する。GitHub Desktop の hardcoded PATH に含まれる `~/.local/bin` を "bridge" として利用する。

## Consequences

- GitHub Desktop Copilot CLI や類似の制約をもつエージェントからも mise 管理ツールが使える
- mise のバージョン切替（`mise use` 等）は透過的（symlink 先が shim のため）
- shim が追加・削除されるたびに再実行が必要だが `run_onchange_after_` により差分検知で自動化されている
- `~/.local/bin` に他ツールのバイナリを置くとき、同名の symlink と衝突する可能性がある（ADR-003 の exclude で一部対策）
