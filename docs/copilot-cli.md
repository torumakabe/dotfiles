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
| `hooks/hooks.json` | preToolUse / postToolUse フック定義 | chezmoi |
| `hooks/scripts/copilot-guard.py` | セキュリティガード（ファイル・URL・環境変数） | chezmoi |
| `hooks/scripts/uv-enforcer.py` | Python / pip 直接実行をブロック | chezmoi |
| `hooks/scripts/audit-log.py` | ツール実行の監査ログ記録 | chezmoi |
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

# copilot-guard: Hook ファイル改変のブロック
echo '{"toolName":"edit","toolArgs":{"path":"/home/user/.copilot/hooks/hooks.json"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py

# copilot-guard: SSH 鍵アクセスのブロック
echo '{"toolName":"bash","toolArgs":{"command":"cat ~/.ssh/id_ed25519"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py

# uv-enforcer: python/pip 直接実行のブロック
echo '{"toolName":"bash","toolArgs":{"command":"python script.py"}}' | uv run ~/.copilot/hooks/scripts/uv-enforcer.py
```

### 自動テスト

```bash
# ユニットテスト（70 テストケース）
uv run -m unittest tests.test_copilot_guard -v
```

CI でも自動実行される（`.github/workflows/test-copilot-guard.yml`）。Hook 関連ファイルの変更時と週次スケジュールで実行し、fail-open リグレッションを検知する。

### Autopilot モードでの安全な利用

`--allow-all` 下ではツール承認・パス権限・URL 権限がすべて無効化されるが、`--deny-tool` と Hooks は引き続き有効である。`.zshrc` に定義された `copilot-safe` エイリアスは、多層防御を固定化した Autopilot 起動設定である。

```bash
copilot-safe -p "YOUR PROMPT"
```

このエイリアスには以下が含まれる:

- `--deny-tool` による外部送信コマンド（curl, wget, nslookup, dig）のブロック（fail-open リスクなし）
- `--secret-env-vars` による機微な環境変数値の隠蔽
- `--max-autopilot-continues 20` による実行ステップ数の上限

ファイルの読み取り・書き込み保護は `--deny-tool` ではなく preToolUse Hook（copilot-guard.py + blocked-files.txt）が担う。`--deny-tool` がサポートする kind は `shell(cmd)`, `write`（パス指定不可）, `url(domain)`, `<MCP>(tool)` のみであり、`read(...)` kind は存在しない。

環境に応じて `--disable-mcp-server` や `--excluded-tools` を追加して攻撃面をさらに縮小できる。

### 監査ログ

`postToolUse` フックにより、ツール実行ごとに `~/.copilot/audit.jsonl` へログが記録される。

```bash
# 直近のツール実行を確認
tail -5 ~/.copilot/audit.jsonl | python3 -m json.tool

# 環境変数 COPILOT_AUDIT_DIR でログ出力先を変更可能
COPILOT_AUDIT_DIR=/path/to/logs copilot
```

### 参考資料

- [GitHub Copilot CLI — Permissions](https://docs.github.com/en/copilot/copilot-cli/using-copilot-cli/permissions) — 公式のパーミッション設計ドキュメント
- [GitHub Copilot CLI — Hooks](https://docs.github.com/en/copilot/copilot-cli/using-copilot-cli/using-copilot-cli-hooks) — 公式の Hooks 設定リファレンス
