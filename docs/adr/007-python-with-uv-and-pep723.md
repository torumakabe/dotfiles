# ADR-007: Python スクリプトは uv run + PEP 723 で実行する

## Status

Accepted

## Context

このリポジトリの Copilot フックやテストには Python スクリプトが多数ある。従来は `python` / `pip` を直接使うと、システム Python と venv のどちらが使われるかがマシン依存になり、依存パッケージも `requirements.txt` 等で別管理になる。

`uv` は高速かつ再現性のある実行を提供し、PEP 723 のインラインスクリプトメタデータ（`# /// script` ブロック）で依存をスクリプト自身に埋め込める。

## Decision

このリポジトリで配布する Python スクリプトは `uv run <script>` で実行する前提とし、依存は PEP 723 のインラインメタデータで宣言する。`python` / `pip` の直接実行は避ける。

テストは `uv run -m unittest ...` で実行する。

## Consequences

- `uv` が実行環境に必須となる（mise で管理）
- 依存が各スクリプトに閉じるためレビュー・コピーが容易
- `uv-enforcer.py` フックがこの規約を実行時に強制する
- システムの Python バージョン差に影響されない
