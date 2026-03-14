# GitHub Copilot CLI Guide

chezmoi は `~/.copilot/` 配下の一部を管理する。プラグインはプラグインマネージャが管理するため chezmoi の対象外である。

## 管理対象ファイル

| ファイル | 用途 | 管理方法 |
|---------|------|----------|
| `copilot-instructions.md` | ユーザーレベルのカスタム指示 | chezmoi |
| `mcp-config.json` | MCP サーバー設定 | chezmoi（`/mcp add` 後は `re-add`） |
| `hooks/hooks.json` | preToolUse フック定義 | chezmoi |
| `hooks/scripts/copilot-guard.py` | セキュリティガード（ファイル・URL・環境変数） | chezmoi |
| `hooks/scripts/uv-enforcer.py` | Python / pip 直接実行をブロック | chezmoi |
| `hooks/blocked-files.txt` | ブロック対象ファイルパターン | chezmoi |
| `hooks/allowed-urls.txt` | URL 許可リスト | chezmoi |
| `skills/` | エージェントスキル | chezmoi（上流更新時は `re-add`） |
| `installed-plugins/` | プラグイン | `/plugin install` で管理 |

## プラグインの管理

プラグインは `/plugin` コマンドで管理する。chezmoi の管理外である。

```text
/plugin marketplace add <publisher>/<plugin>
/plugin install <name>@<plugin>
/plugin update <name>@<plugin>
```

例: [Azure Skills Plugin](https://github.com/microsoft/azure-skills)

```text
/plugin marketplace add microsoft/azure-skills
/plugin install azure@azure-skills
/plugin update azure@azure-skills
```

前提: Node.js 18+、Azure CLI (`az login`)、Azure Developer CLI (`azd auth login`) が必要である。

## スキルの管理

ユーザーレベルのスキル（`~/.copilot/skills/`）は chezmoi で管理する。

```bash
npx skills add -g <owner>/<repo>/<path>
chezmoi re-add ~/.copilot/skills/<skill-name>

npx skills add -g <owner>/<repo>/<path>
chezmoi re-add ~/.copilot/skills/<skill-name>
chezmoi diff
```

現在インストール済みのスキル:

| スキル | ソース | 用途 |
|--------|--------|------|
| `microsoft-skill-creator` | [github/awesome-copilot](https://github.com/github/awesome-copilot) (MIT) | MS Learn MCP を使って Microsoft 技術のスキルを生成 |

## フックのテスト

フックは stdin に JSON を受け取り、stdout に許可 / 拒否の JSON を返す。

```bash
# copilot-guard: ファイル・URL アクセス制御
echo '{"toolName":"edit","toolArgs":{"path":".env"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py

# copilot-guard: 環境変数アクセスのブロック（bash ツールのみ対象）
echo '{"toolName":"bash","toolArgs":{"command":"printenv"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py
echo '{"toolName":"bash","toolArgs":{"command":"echo $GITHUB_TOKEN"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py

# copilot-guard: 安全な変数参照は許可
echo '{"toolName":"bash","toolArgs":{"command":"echo $HOME"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py

# uv-enforcer: python/pip 直接実行のブロック
echo '{"toolName":"bash","toolArgs":{"command":"python script.py"}}' | uv run ~/.copilot/hooks/scripts/uv-enforcer.py
```
