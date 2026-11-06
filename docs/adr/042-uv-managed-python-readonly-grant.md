# ADR-042: GitHub Copilot CLI の sandbox で uv 管理 Python root を読み取り専用にする

## Status

Accepted

## Context

sandbox 内で `uv run` が uv 管理 Python を使うには、interpreter と標準ライブラリを読み取る必要がある。macOS の GitHub Copilot CLI 1.0.106-8 では、root の読み取り許可がないと `uv run --managed-python` が失敗し、許可すると成功した。

root への書き込み許可を加えれば、sandbox 内で uv が Python を自動導入できる可能性がある。しかし Windows の GitHub Copilot CLI の local sandbox では、書き込みを許可した保存先でも、uv が導入時に作る junction の作成が拒否された。Cloud の sandbox では、`uv run` が必要な Python を自動導入できた。

## Decision

GitHub Copilot CLI の設定同期では、`uv python dir` が返す root を `readonlyPaths` に追加する。書き込みは許可しない。必要な Python は sandbox の外で事前に導入する。Cloud では、`uv run` による必要時の自動導入を使う。

uv が未導入の端末では、警告して root の追加を省略する。`uv python dir` が失敗した場合は設定同期を停止する。

## Consequences

- local sandbox 内からは Python を自動導入できない。事前導入していない版を求める `uv run` は失敗する。
- 読み取り許可は、uv 以外の sandbox 内プロセスにも及ぶ。
