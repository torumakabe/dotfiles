# ADR-038: Windows sandbox で uv.toml だけを読み取り専用にする

## Status

Accepted

## Context

uv の設定ファイルを sandbox 内から読み取るには、対象ファイルへの読み取り許可が必要になる。
`readonlyPaths` は uv だけでなく sandbox 内のすべてのプロセスに適用される。

## Decision

Windows の sandbox 設定同期はユーザーの `%APPDATA%\uv\uv.toml` の絶対パスだけを `readonlyPaths` に追加する。親の `uv` ディレクトリは許可せず、ファイルの存在や内容を確認しない。ほかの環境と既存 policy entry は変更しない。

## Consequences

- sandbox 内の全 process がこのファイルを読み取れるが、書き込めない。
- ファイルに認証情報が含まれる場合、それらも sandbox 内のすべてのプロセスから読み取り可能になる。
- sandbox の同期は既存の読み取り許可を保持し、同じファイル path を重複して追加しない。
- ADR-026 の「共有 `uv.toml` を追加許可しない」という判断を、Windows のこのファイルに限って置き換える。
