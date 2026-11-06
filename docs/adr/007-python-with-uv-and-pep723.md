# ADR-007: Python スクリプトは uv run + PEP 723 を原則とする

## Status

Accepted

command hook の固定 interpreter とフックによる実行時強制は [ADR-041](041-copilot-hooks-retirement.md) で廃止した。通常のスクリプトの方針は引き続き有効とする。

## Context

このリポジトリのテストなどには Python スクリプトが多数ある。`python` / `pip` を直接使うと、実行環境と依存管理がマシン依存になる。

`uv` と PEP 723 のインラインメタデータは、通常のスクリプトに再現性と自己完結した依存宣言を提供する。

## Decision

通常の Python スクリプトは `uv run <script>` で実行し、依存と `requires-python` は PEP 723 のインラインメタデータで宣言する。`python` / `pip` の直接実行は避ける。

テストは `uv run -m unittest ...` で実行する。

## Consequences

- 通常のスクリプト実行には uv が必要になる
- 依存が各スクリプトに閉じるため、レビューとコピーが容易になる
- フックによる実行時強制は行わない
- sandbox 内で使用する Python の導入条件は ADR-042 に従う
