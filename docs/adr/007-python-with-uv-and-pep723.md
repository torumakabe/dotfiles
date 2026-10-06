# ADR-007: Python スクリプトは uv run + PEP 723 を原則とする

## Status

Accepted

## Context

このリポジトリのフックやテストには Python スクリプトが多数ある。`python` / `pip` を直接使うと、実行環境と依存管理がマシン依存になる。

`uv` と PEP 723 のインラインメタデータは、通常のスクリプトに再現性と自己完結した依存宣言を提供する。

一方、Copilot CLI command hook から Windows ProcessContainer sandbox 内で mise や uv を起動すると、隔離された mise の config、state、downloads が必要になり失敗する。command hook は起動経路を固定する必要がある。

## Decision

通常の Python スクリプトは `uv run <script>` で実行し、依存と `requires-python` は PEP 723 のインラインメタデータで宣言する。`python` / `pip` の直接実行は避ける。

テストは `uv run -m unittest ...` で実行する。

Copilot CLI command hook は例外とする。chezmoi apply 時に `uv python install 3.14` を実行し、`uv python find --managed-python 3.14` が返す managed interpreter の安定した絶対パスを `~/.copilot/hooks/python-runtime.env` に記録する。hook 実行時は OS 別 launcher がこの interpreter を直接起動し、mise と uv を経由しない。

hook scripts は標準ライブラリだけを使用する。PEP 723 の `requires-python` は実行経路にかかわらず維持する。

## Consequences

- 通常の実行と Python 3.14 の provision に uv が必須となる
- 依存が各スクリプトに閉じるためレビュー・コピーが容易
- `uv-enforcer.py` フックがこの規約を実行時に強制する
- command hook は sandbox 内の mise/uv の状態に依存せず起動できる
- launcher、runtime env、managed interpreter の同期が必要になる
