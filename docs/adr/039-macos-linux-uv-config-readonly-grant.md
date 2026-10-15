# ADR-039: macOS/Linux sandbox で uv.toml だけを読み取り専用にする

## Status

Accepted

## Context

“ですよね。windowsと同じ効果を得られるようにしてください。”

ADR-026 は共有 `uv.toml` の readonly grant を採用しないとした。ADR-038 は Windows でユーザーの uv 設定ファイルだけを許可した。

## Decision

macOS/Linux の sandbox 設定同期では、有効な絶対 `XDG_CONFIG_HOME` があればそこから、未設定・空・相対パスなら `$HOME/.config` から求めた `uv/uv.toml` だけを `readonlyPaths` に追加する。親ディレクトリは許可せず、既存のユーザー所有 `readonlyPaths` entry は保持する。

## Consequences

- sandbox 内のプロセスは uv 設定ファイルを読み取れるが、書き込めない。
- ADR-026 の判断を macOS/Linux のこのファイルに限って置き換え、ADR-038 と同じ範囲の許可を適用する。
