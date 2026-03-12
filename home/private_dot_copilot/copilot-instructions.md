# Copilot Instructions (User-Level)

## ツール操作の制約（デフォルト動作より優先）

- ファイルをエディタで開く → `Start-Process edit <path>`（Microsoft Edit が別ウィンドウで起動する）
- Python 実行・パッケージ管理 → 常に `uv` 経由。`python` / `pip` の直接実行は禁止（preToolUse フックで強制）
  - スクリプト実行: `uv run`（`python3` / `python` は不可）
  - パッケージ管理: `uv add` / `uv pip`（`pip` / `pip3` は不可）
  - 仮想環境: `uv venv`（`python -m venv` は不可）
- コマンド存在チェック → `command -v`（`which` は使わない）
- Copilot CLI のシェルセッションでは `$PROFILE` が読み込まれないため、エイリアスや関数は使えない

## 言語

- 日本語で応答する（文脈上明らかに英語が必要な場合を除く）
- コードコメント: 個人プロジェクトは日本語、OSS 貢献は英語

## 基本方針

- 簡潔さと可読性を重視（巧妙さより）
- 既存のツール・パターンを使う（車輪の再発明を避ける）
- 複数アプローチがある場合はトレードオフを説明

## コーディング規約

### シェルスクリプト

- bash スクリプトでは `set -euo pipefail` を使う
- bash 固有の機能が必要でない限り POSIX 互換構文を優先

### Python

- 対象バージョン: Python 3.9+（幅広い互換性のため）
- 型ヒントを使う（PEP 484 / 3.10+ では PEP 604 の union 構文）
- 外部依存より標準ライブラリを優先
- `uv run` で実行する単一ファイルスクリプトには PEP 723 インラインメタデータを使う

### インフラ / クラウド

- プライマリクラウド: Azure
- 自動化にはポータルより Azure CLI (`az`) を優先

### Git

- Conventional Commits 形式でコミットメッセージを書く
- SSH キーでコミットに署名（1Password 管理）
