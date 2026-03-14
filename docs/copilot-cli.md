# GitHub Copilot CLI Guide

GitHub Copilot CLI の設定・運用ガイドである。chezmoi が `~/.copilot/` 配下のカスタム指示、フック、スキルを管理する。プラグインは Copilot CLI のプラグインマネージャが管理するため chezmoi の対象外である。

このガイドでは以下を扱う。

- **管理対象ファイル**: chezmoi で管理するファイルと管理外のファイルの一覧
- **プラグイン / スキル**: 追加・更新の手順
- **セキュリティフック**: 設定のカスタマイズとテスト方法（設計の詳細は [`docs/architecture.md`](architecture.md#copilot-guard-の設計) を参照）

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

> **注意**: Azure Skills Plugin は Node.js 18+、Azure CLI (`az login`)、Azure Developer CLI (`azd auth login`) が前提である。他のプラグインの前提条件は各プラグインのドキュメントを参照する。

## スキルの管理

ユーザーレベルのスキル（`~/.copilot/skills/`）は chezmoi で管理する。

```bash
npx skills add -g <owner>/<repo>/<path>
chezmoi re-add ~/.copilot/skills/<skill-name>
chezmoi diff
```

現在インストール済みのスキル:

| スキル | ソース | 用途 |
|--------|--------|------|
| `microsoft-skill-creator` | [github/awesome-copilot](https://github.com/github/awesome-copilot) (MIT) | MS Learn MCP を使って Microsoft 技術のスキルを生成 |

## セキュリティフック

コーディングエージェントは `bash` ツールを通じてファイル読み取りやコマンド実行を行える。便利な一方で、秘匿情報の意図しない読み取りや外部送信のリスクがある。このリポジトリでは `preToolUse` フックで **ツール実行前に検査し、危険な操作を自動拒否する** ガードを提供している。

脅威モデル、多層防御の構造、各チェック層の判定ロジックについては [`docs/architecture.md` の Copilot Guard セクション](architecture.md#copilot-guard-の設計) を参照する。

### 設定ファイルのカスタマイズ

#### blocked-files.txt

ブロック対象のファイルパスをグロブパターンで記述する。1 行 1 パターン、`#` で始まる行はコメント。

**パターン記法**:

| 記法 | 意味 | 例 |
|------|------|------|
| `*` | 1 つのパスセグメント内の任意の文字列 | `*.pem` → `server.pem` にマッチ |
| `?` | 1 つのパスセグメント内の任意の 1 文字 | `?.key` → `a.key` にマッチ |
| `**` | パスセグメントをまたぐ任意の文字列 | `**/.env` → `src/app/.env` にマッチ |
| `**/` | 0 個以上のディレクトリプレフィックス | `**/.azure/*` → `.azure/config` にも `a/b/.azure/config` にもマッチ |

**パス正規化**: マッチング前に `\` → `/` への変換、連続 `/` の圧縮、先頭 `./` の除去、`file://` URI の展開が行われる。Windows パス（`C:\Users\...`）も正しくマッチする。

#### allowed-urls.txt

許可するドメインを 1 行 1 つ記述する。サブドメインも自動的に許可される（例: `github.com` は `api.github.com` も許可）。全行コメントアウトすると URL チェック自体が無効になる。

### フックのテスト

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
