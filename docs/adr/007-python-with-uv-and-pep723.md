# ADR-007: Python スクリプトは uv run + PEP 723 を原則とする

## Status

Accepted

command hook の固定 interpreter とフックによる実行時強制は [ADR-041](041-copilot-cli-hooks-retirement-and-uv-sandbox.md) で廃止した。通常のスクリプトの方針は引き続き有効とする。

## Context

このリポジトリのテストなどには Python スクリプトが多数ある。`python` / `pip` を直接使うと、実行環境と依存管理がマシン依存になる。

`uv` と PEP 723 のインラインメタデータは、通常のスクリプトに再現性と自己完結した依存宣言を提供する。

当時は Copilot CLI command hook から Windows ProcessContainer sandbox 内で mise や uv を起動すると、隔離された mise の config、state、downloads が必要になり失敗した。対策として、`chezmoi apply` 時に `uv python install 3.14` を実行し、`uv python find --managed-python 3.14` が返す interpreter の絶対パスを `~/.copilot/hooks/python-runtime.env` に記録した。hook 実行時は OS 別 launcher がこの interpreter を直接起動し、mise と uv を経由しなかった。

hook scripts は標準ライブラリだけを使い、PEP 723 の `requires-python` も維持した。`uv-enforcer.py` は `python` / `pip` の直接実行を拒否していた。これらのフックに関する仕組みは ADR-041 で廃止した。

## Decision

通常の Python スクリプトは `uv run <script>` で実行し、依存と `requires-python` は PEP 723 のインラインメタデータで宣言する。`python` / `pip` の直接実行は避ける。

テストは `uv run -m unittest ...` で実行する。

## Consequences

- 通常のスクリプト実行には uv が必要になる
- 依存が各スクリプトに閉じるため、レビューとコピーが容易になる
- フックによる実行時強制は行わない
- sandbox 内で使用する Python の導入条件は ADR-041 に従う
