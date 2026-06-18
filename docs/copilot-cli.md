# GitHub Copilot CLI Guide

この repo では `~/.copilot/` 配下のうち、**自分で維持したい設定だけ** を chezmoi で管理する。Copilot CLI 自体の一般的な使い方や `/plugin` の詳細は公式ドキュメントを参照。

## 管理境界

`~/.copilot/` 配下のうち chezmoi 管理対象:

- `copilot-instructions.md` — ユーザーレベルのカスタム指示
- `mcp-config.json` — 手動 MCP サーバー設定（`/mcp add` 後は `chezmoi re-add`）
- `hooks/hooks.json` / `hooks/scripts/*.py` — `preToolUse` / `postToolUse` / `postToolUseFailure` フック（`copilot-guard.py`, `uv-enforcer.py`, `node-global-enforcer.py`, `audit-log.py`, `audit-failure.py`）
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

`agentfinder` は GitHub Agent Finder (`https://agentfinder.github.com/api/v1/search`) を使って、MCP サーバー、ツール、スキル、エージェントを検索する手動追加スキル。
GitHub Docs の Agent Finder 手順に従い、`home/private_dot_copilot/skills/agentfinder/SKILL.md` を `~/.copilot/skills/agentfinder/SKILL.md` として配置する。
利用時は `/agentfinder <探したい連携や作業>` を実行し、返された候補はユーザーが明示的に選ぶまで自動インストールしない。

## セキュリティフック

`preToolUse` で以下を検査する。設計は [`architecture.md`](architecture.md#copilot-guard-の設計) を参照。

- `copilot-guard.py`: 秘匿ファイル (`blocked-files.txt`) / 確認付き (`ask-files.txt`) / URL 許可 (`allowed-urls.txt`) / 機微な環境変数の読み取り
- `uv-enforcer.py`: `python` / `pip` の直接実行を抑止
- `node-global-enforcer.py`: `npm` / `yarn` / `pnpm` のグローバルインストールを抑止

パターンファイルは 1 行 1 パターン、`#` でコメント。パス比較は `\` → `/` に正規化、`deny > ask > allow`。`allowed-urls.txt` は全行コメントアウトで無効化できる。

`copilot-guard.py` の `blocked-files.txt` チェックは `view` / `edit` 系ツールだけでなく **`bash`/`powershell` ツール内の `cat` / `Get-Content` 等のシェル経由参照にも適用される**。これは CLI 本体のパス検出が shell コマンド内に埋め込まれたパスを十分に追えない（公式ドキュメントの "Path detection for shell commands has limitations" 記載）穴を Hook で塞ぐ意図的な設計である（ADR-006 / ADR-010 と整合）。

動作確認:

```bash
echo '{"toolName":"edit","toolArgs":{"path":".env"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py
uv run -m unittest tests.test_copilot_guard -v
```

## `copilot-guardrails`

`.zshrc` / `PowerShell_profile.ps1` の `copilot-guardrails` は、Copilot CLI の利便性（`--allow-all`）とセキュリティ（`--deny-tool` での外部送信系制限、`--secret-env-vars` での環境変数隠蔽）のバランスを取った起動ラッパー。起動モード（interactive / plan / autopilot）は固定しない。記法は `copilot help permissions` と公式ドキュメント参照。

設計上の前提と限界:

- `--allow-all` は `--allow-all-tools` + `--allow-all-paths` + `--allow-all-urls` を含意し、**`--deny-url` / `--allow-url` および `~/.copilot/config.json` の `deniedUrls` を無効化する**。URL ブロックは `--deny-tool 'url(...)'`（`--allow-all` 下でも優先される）で行うこと。
- `--deny-tool 'shell(cmd:*)'` はシェルコマンドラインの**先頭トークン**に対するプレフィックス一致であり、`bash` ツール自体や内部で実行される一般コマンドは止めない。ツール実装ごと止めたい場合は `--excluded-tools <tool>` を使う。
- `--deny-tool 'memory'` はビルトインに該当ツールが存在しないため no-op（v1.0.49 時点の検証）。
- `/share gist`（`--share-gist`）は **ユーザー直接コマンドのため preToolUse Hook の対象外**。`--allow-all` 下で秘匿情報がエージェントのコンテキストに入った状態で実行すると、secret Gist として外部化され得る。非 EMU 環境では技術的に防ぐ手段が無いため、運用ルール（実行前に `/reset-allowed-tools` で承認状態をクリアする等）で補う。
- `permissionRequest` / `notification` / `userPromptSubmitted` 等の Hook タイプは現状未使用。`--allow-all` を外して承認を自動化する運用に切り替える場合の拡張余地として記録しておく。

## 監査ログ

用途別に 3 ファイル。`COPILOT_AUDIT_DIR` で出力先を変更できる。

| ファイル | 記録内容 | 書込元 |
|---|---|---|
| `~/.copilot/audit.jsonl` | ツール実行成功履歴 | `postToolUse` → `audit-log.py` |
| `~/.copilot/audit-denies.jsonl` | `copilot-guard.py` が deny 判定した呼び出し（URL/env/blocked-files/secrets 等）| `preToolUse` → `copilot-guard.py` |
| `~/.copilot/audit-failures.jsonl` | ツールハンドラーが返したエラー（例: `view` の path 不在） | `postToolUseFailure` → `audit-failure.py` |

```bash
tail -5 ~/.copilot/audit.jsonl | uv run python -m json.tool
tail -5 ~/.copilot/audit-denies.jsonl
tail -5 ~/.copilot/audit-failures.jsonl
```

> `shell` ツールが起動したコマンドの非 0 exit は `postToolUseFailure` の対象外（成功扱い）。検証済み (v1.0.35-4, 2026-04-23)。
>
> `audit-denies.jsonl` は **`copilot-guard.py` の deny のみ**を記録する。`uv-enforcer.py` / `node-global-enforcer.py` の deny（グローバル install 系・python 直接実行系）は監査対象外（= プロンプト履歴のみに残る）。理由: これらは「絶対ブロック対象の既知パターン」であり、事後監査より即時ブロック自体が目的のため。

## 参考

- [GitHub Copilot CLI — Permissions](https://docs.github.com/en/copilot/copilot-cli/using-copilot-cli/permissions)
- [GitHub Copilot CLI — Hooks](https://docs.github.com/en/copilot/copilot-cli/using-copilot-cli/using-copilot-cli-hooks)
