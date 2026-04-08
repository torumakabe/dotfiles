# GitHub Copilot CLI Guide

この repo では `~/.copilot/` 配下のうち、**自分で維持したい設定だけ** を chezmoi で管理する。Copilot CLI 自体の一般的な使い方や `/plugin` の詳細は公式ドキュメントを参照。

## 管理境界

| パス | 用途 | 管理方法 |
|------|------|----------|
| `copilot-instructions.md` | ユーザーレベルのカスタム指示 | chezmoi |
| `mcp-config.json` | 手動 MCP サーバー設定 | chezmoi (`/mcp add` 後は `chezmoi re-add`) |
| `hooks/hooks.json` | `preToolUse` / `postToolUse` 設定 | chezmoi |
| `hooks/scripts/copilot-guard.py` | ファイル・URL・環境変数アクセスのガード | chezmoi |
| `hooks/scripts/uv-enforcer.py` | `python` / `pip` 直接実行の抑止 | chezmoi |
| `hooks/scripts/audit-log.py` | ツール実行ログの記録 | chezmoi |
| `hooks/blocked-files.txt` | deny パターン | chezmoi |
| `hooks/ask-files.txt` | ask パターン | chezmoi |
| `hooks/allowed-urls.txt` | URL 許可リスト | chezmoi |
| `skills/` | ユーザーレベルのスキル（手動管理分） | chezmoi |
| `installed-plugins/` | プラグイン | Copilot CLI 側で管理 |

## CLI 本体の導入元

| 環境 | 導入元 |
|------|--------|
| Linux / WSL / Codespaces / Dev Container | `mise` |
| macOS | `brew` |
| Windows | `winget` (`reference/windows/configuration.dsc.yaml`) |

macOS では Copilot Desktop からも参照できるよう、`.zshrc` で `COPILOT_CLI_PATH` を公開する。

## プラグインとスキル

- **プラグイン**: `/plugin` コマンドで管理する。chezmoi の管理外
- **スキル**: プラグイン由来のスキルはプラグイン側で管理される。手動追加のスキルのみ `~/.copilot/skills/` を chezmoi で管理する

### 手動スキルの追加

プラグインに含まれないスキルを手動で追加する場合、外部スキルの取り込みまたは自作する。

```bash
# 外部スキルの取り込み
npx skills add -g <owner>/<repo>/<path>

# 自作の場合は ~/.copilot/skills/<skill-name>/SKILL.md を作成
```

いずれも chezmoi ソースへ戻す。

```bash
chezmoi re-add ~/.copilot/skills/<skill-name>
chezmoi diff
```

## セキュリティフック

この repo では `preToolUse` フックで、ツール実行前に次を検査する。

- **秘匿ファイルの拒否**: `blocked-files.txt`
- **確認付きアクセス**: `ask-files.txt`
- **許可外 URL の拒否**: `allowed-urls.txt`
- **機微な環境変数の読み取り拒否**: `copilot-guard.py`
- **`python` / `pip` 直接実行の拒否**: `uv-enforcer.py`

判定の詳細な設計は [`docs/architecture.md`](architecture.md#copilot-guard-の設計) を参照。

### ガード用ファイルの編集

- `blocked-files.txt` と `ask-files.txt` は 1 行 1 パターン
- `#` 始まりの行はコメント
- パス比較前に `\` は `/` へ正規化される
- 同じパスが両方に当たる場合は **deny が優先**

`allowed-urls.txt` は 1 行 1 ドメイン。全行コメントアウトすると URL チェックを無効化できる。

## フックの確認

```bash
# ファイル・URL・環境変数アクセス
echo '{"toolName":"edit","toolArgs":{"path":".env"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py
echo '{"toolName":"bash","toolArgs":{"command":"echo $GITHUB_TOKEN"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py

# python/pip 直接実行の抑止
echo '{"toolName":"bash","toolArgs":{"command":"python script.py"}}' | uv run ~/.copilot/hooks/scripts/uv-enforcer.py
```

自動テスト:

```bash
uv run -m unittest tests.test_copilot_guard -v
```

## `copilot-safe`

`.zshrc` / `PowerShell_profile.ps1` の `copilot-safe` は、Autopilot での事故を減らすための起動ラッパーである。主に次を固定する。

- `--deny-tool` による外部送信系コマンドの制限
- `--secret-env-vars` による機微な環境変数の隠蔽
- `--max-autopilot-continues 20` による連続実行数の上限

`--deny-tool` の具体的な記法や制限は `copilot help permissions` と公式ドキュメントを参照。

## 監査ログ

`postToolUse` フックで `~/.copilot/audit.jsonl` に記録する。

```bash
tail -5 ~/.copilot/audit.jsonl | uv run python -m json.tool
COPILOT_AUDIT_DIR=/path/to/logs copilot
```

## 参考

- [GitHub Copilot CLI — Permissions](https://docs.github.com/en/copilot/copilot-cli/using-copilot-cli/permissions)
- [GitHub Copilot CLI — Hooks](https://docs.github.com/en/copilot/copilot-cli/using-copilot-cli/using-copilot-cli-hooks)
