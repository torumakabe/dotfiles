# GitHub Copilot CLI Guide

この repo では `~/.copilot/` 配下のうち、**自分で維持したい設定だけ** を chezmoi で管理する。Copilot CLI 自体の一般的な使い方や `/plugin` の詳細は公式ドキュメントを参照。

## 管理境界

`~/.copilot/` 配下のうち chezmoi 管理対象:

- `copilot-instructions.md` — ユーザーレベルのカスタム指示
- `mcp-config.json` — 手動 MCP サーバー設定（`/mcp add` 後は `chezmoi re-add`）
- `hooks/hooks.json` / `hooks/scripts/*.py` — `preToolUse` / `postToolUse` フック（`copilot-guard.py`, `uv-enforcer.py`, `audit-log.py`）
- `hooks/{blocked-files,ask-files,allowed-urls}.txt` — アクセス制御リスト
- `skills/` — 手動追加分のみ（プラグイン由来は対象外）

管理外: `installed-plugins/`（Copilot CLI 側で管理）。

## CLI 本体の導入元

| 環境 | 導入元 |
|------|--------|
| Linux / WSL / Codespaces / Dev Container | 公式インストールスクリプト (`gh.io/copilot-install`) |
| macOS | `brew` |
| Windows | `winget` (`reference/windows/configuration.dsc.yaml`) |

更新は全 OS で `copilot update`。macOS では Copilot Desktop から参照できるよう、`.zshrc` で `COPILOT_CLI_PATH` を公開する。

## LSP サーバー

`~/.copilot/lsp-config.json` (chezmoi 管理) で設定する。Python 向け `ty` (Astral) は mise バックエンドがないため `uv tool install ty`（`run_once` で自動化）、TypeScript 等の npm パッケージは mise の `npm:` バックエンドで管理する。

## プラグインとスキル

プラグインは `/plugin` で管理（chezmoi 管理外）。プラグイン由来のスキルはプラグイン側で管理され、手動追加分のみ `~/.copilot/skills/` を chezmoi で管理する。

```bash
# 外部スキルの取り込み（または ~/.copilot/skills/<skill-name>/SKILL.md を自作）
npx skills add -g <owner>/<repo>/<path>
chezmoi re-add ~/.copilot/skills/<skill-name>
```

## セキュリティフック

`preToolUse` で以下を検査する。設計は [`architecture.md`](architecture.md#copilot-guard-の設計) を参照。

- `copilot-guard.py`: 秘匿ファイル (`blocked-files.txt`) / 確認付き (`ask-files.txt`) / URL 許可 (`allowed-urls.txt`) / 機微な環境変数の読み取り
- `uv-enforcer.py`: `python` / `pip` の直接実行を抑止

パターンファイルは 1 行 1 パターン、`#` でコメント。パス比較は `\` → `/` に正規化、`deny > ask > allow`。`allowed-urls.txt` は全行コメントアウトで無効化できる。

動作確認:

```bash
echo '{"toolName":"edit","toolArgs":{"path":".env"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py
uv run -m unittest tests.test_copilot_guard -v
```

## `copilot-cruise`

`.zshrc` / `PowerShell_profile.ps1` の `copilot-cruise` は Autopilot 起動ラッパー。`--deny-tool`（外部送信系の制限）、`--secret-env-vars`（環境変数隠蔽）、`--max-autopilot-continues 20` を固定する。記法は `copilot help permissions` と公式ドキュメント参照。

## 監査ログ

`postToolUse` フックで `~/.copilot/audit.jsonl` に記録。`COPILOT_AUDIT_DIR` で出力先を変更できる。

```bash
tail -5 ~/.copilot/audit.jsonl | uv run python -m json.tool
```

## 参考

- [GitHub Copilot CLI — Permissions](https://docs.github.com/en/copilot/copilot-cli/using-copilot-cli/permissions)
- [GitHub Copilot CLI — Hooks](https://docs.github.com/en/copilot/copilot-cli/using-copilot-cli/using-copilot-cli-hooks)
