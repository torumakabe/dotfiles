# GitHub Copilot CLI Guide

この repo では `~/.copilot/` 配下のうち、**自分で維持したい設定だけ** を chezmoi で管理する。Copilot CLI 自体の一般的な使い方や `/plugin` の詳細は公式ドキュメントを参照。

## 管理境界

`~/.copilot/` 配下のうち chezmoi 管理対象:

- `copilot-instructions.md` — ユーザーレベルのカスタム指示
- `mcp-config.json` — 手動 MCP サーバー設定（`/mcp add` 後は `chezmoi re-add`）
- `settings.json` の実験機能、プラグイン、sandbox 設定 — `run_onchange_after_35-configure-copilot-sandbox.*` で既存設定へマージ
- `hooks/hooks.json` / `hooks/scripts/*.py` — `preToolUse` / `postToolUse` / `postToolUseFailure` フック（`copilot-guard.py`, `uv-enforcer.py`, `node-global-enforcer.py`, `audit-log.py`, `audit-failure.py`）
- `hooks/{allowed-files,blocked-files,ask-files}.txt` — ファイルアクセス制御リスト
- `skills/` — 手動追加分のみ（プラグイン由来は対象外）

管理外: `installed-plugins/` と `plugin-data/`（Copilot CLI 側で管理）。

## CLI 本体の導入元

| 環境 | 導入元 |
|------|--------|
| Linux / WSL / Codespaces / Dev Container | 固定した公式リリースアーカイブを SHA-256 検証（[`docs/operations.md`](operations.md#bootstrap--shell-pin-の更新)） |
| macOS | `brew` |
| Windows | `winget` (`reference/windows/configuration.dsc.yaml`) |

更新は全 OS で `copilot update`。

Codespaces / Dev Container のベースイメージには `/usr/local/bin/copilot` が同梱されていることがあり、`copilot update` の対象外のまま古くなる。このため導入判定は `command -v copilot` ではなく `~/.local/bin/copilot` の実体で行う（[`docs/troubleshooting.md`](troubleshooting.md#codespaces--dev-container-で-copilot-のバージョンが古い)）。

## LSP サーバー

`~/.copilot/lsp-config.json` (chezmoi 管理) で設定する。Python 向け `ty` (Astral) は mise バックエンドがないため `uv tool install ty`（`run_once` で自動化）、TypeScript 等の npm パッケージは mise の `npm:` バックエンドで管理する。

## プラグインとスキル

chezmoi は `settings.json` で追加 marketplace と有効なプラグインを宣言する。Copilot CLI は宣言されたプラグインの導入とセッション開始時の更新を担当し、導入実体とキャッシュは chezmoi で管理しない。プラグインに含めない外部 skill は `gh skill` で管理し、自作 skill と公式の導入コマンドを持たない skill だけを `~/.copilot/skills/` から chezmoi へ取り込む。

```bash
# GitHub Copilot の user scope へ外部 skill を導入する
gh skill install <owner>/<repo> <skill-name> --agent github-copilot --scope user
```

`personal-skills@torumakabe-agent-plugins` は `agentfinder`、`japanese-technical-writing`、`lsp-setup` を提供する。利用時はスキル名を指定する。`agentfinder` が返した候補は、ユーザーが明示的に選ぶまで自動インストールしない。

`gh-stack` は Stacked PR の設計と `gh stack` の非対話操作を Copilot に教える公式 skill である。セットアップスクリプトは、公式 skill と対応する GitHub CLI extension が未導入の場合だけ `github/gh-stack` から取得する。Stacked PR を提案する条件は `copilot-instructions.md`、操作方法は公式 skill を正本とする。管理境界は [ADR-024](adr/024-gh-stack-distribution-and-updates.md)、更新手順は [operations.md](operations.md#gh-stack-の更新) を参照する。

## セキュリティフック

`preToolUse` で以下を検査する。設計は [`architecture.md`](architecture.md#copilot-guard-の設計) を参照。

- `copilot-guard.py`: ファイル操作と読み取り専用検索のプロジェクト相対パス例外 (`allowed-files.txt`) / 秘匿ファイル (`blocked-files.txt`) / 確認付き (`ask-files.txt`) / 機微な環境変数の読み取り / `git commit` の明示承認
- `uv-enforcer.py`: `python` / `pip` の直接実行を抑止
- `node-global-enforcer.py`: `npm` / `yarn` / `pnpm` のグローバルインストールを抑止

パターンファイルは 1 行 1 パターン、`#` でコメント。パス比較は `\` → `/` に正規化する。判定の優先度は `deny > ask > no opinion（空出力）` とし、`allow` は出力しない（[ADR-006](adr/006-pretooluse-hook-no-allow.md)）。

`copilot-guard.py` の `blocked-files.txt` チェックはパス引数を持つツールだけでなく **`bash`/`powershell` ツール内の `cat` / `Get-Content` 等のシェル経由参照にも適用される**。これは CLI 本体のパス検出が shell コマンド内に埋め込まれたパスを十分に追えない（公式ドキュメントの "Path detection for shell commands has limitations" 記載）穴を Hook で塞ぐ意図的な設計である。

`allowed-files.txt` の例外を適用するツールは、ファイル操作の `view`、`apply_patch`、`edit`、`create`、`write` と、読み取り専用検索の `rg`、`glob` に限定する。`allowed-files.txt` の各行はワイルドカードのない単一のプロジェクト相対パスとし、ワイルドカードを含む行は例外として扱わない。`rg` の `paths` で許可ファイルを直接指定した場合は、ファイル操作ツールと同じ判定を使う。`rg` の `glob` / `globs` と `glob` の `pattern` は、ワイルドカードを含まず `allowed-files.txt` のパスと一致し、明示された `paths` がすべてプロジェクト内にある場合だけ例外を適用する。`paths` を省略した場合は Hook のプロセス作業ディレクトリを検索ルートとする。シェルコマンド、プロジェクト外の検索ルート、シンボリックリンクまたはジャンクションを含むパス、file URI、`..` を含むパス、未知のツールには例外を適用しない。一つのツール呼び出しに許可対象と拒否対象のパスが混在する場合は、呼び出し全体を拒否する。

すべての command Hook は `cwd: "."` でリポジトリルートから起動する。guard は許可対象ツールの絶対パスをそのルートに対して判定し、audit Hook は同じルートを操作元として記録する。PreToolUse 入力の `cwd` は、Copilot Workspace セッションで GitHub Copilot のインストール先になる場合があるため、判定には使わない。

Copilot CLI は Hook 設定をセッション開始時に読み込む。`hooks.json` を配備した後、既存セッションへ `cwd` の変更を反映するにはセッションを再起動する。ただし、Copilot Workspace が再開したセッションでは、再起動後も `cwd: "."` が GitHub Copilot のインストール先へ解決される場合がある。この状態では guard が対象ファイルをプロジェクト外と判定して拒否する。別のリポジトリにある同名ファイルを許可しないため、対象パスからプロジェクトルートを推測せず、新規 Workspace セッションへ移行する。

動作確認:

```bash
echo '{"toolName":"edit","toolArgs":{"path":".env"}}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py
uv run -m unittest tests.test_copilot_guard -v
```

## `copilot-guardrails`

`.zshrc` / `PowerShell_profile.ps1` の `copilot-guardrails` は、Copilot CLI の利便性（`--allow-all`）と `--secret-env-vars` による環境変数隠蔽を固定する起動ラッパー。起動モード（interactive / plan / autopilot）は固定しない。

設計上の前提と限界:

- `--allow-all` はツール権限の承認を省略するが、local sandbox の有効状態は変更しない。Copilot CLI が sandbox 外での再実行方法を常に提示するとは限らない。
- local sandbox は shell command と filesystem policy を対象とする。MCP と LSP は対象外であり、Copilot CLI 組み込みファイルツールの filesystem policy は software-only safeguard である。
- `run_onchange_after_35-configure-copilot-sandbox.*` は `~/.copilot/settings.json` の他のキーと既存 filesystem path rules を保ったまま設定を更新する。投入値は `home/.chezmoitemplates/copilot-user-settings.json` を正本とする。
- `sandbox.enabled` の初回値、設定保持、組織管理設定との優先関係は [`operations.md`](operations.md#copilot-local-sandbox-の既定値) を参照する。判断は [ADR-026](adr/026-copilot-cli-sandbox-environment-defaults-and-explicit-setting-preservation.md) に記録する。
- Linux 系の bubblewrap 診断は `sandbox.enabled` が `true` または未設定の場合に実行し、`false` の場合は probe を省略する。
- `--deny-tool 'memory'` はビルトインに該当ツールが存在しないため no-op（v1.0.49 時点の検証）。
- `/share gist`（`--share-gist`）は **ユーザー直接コマンドのため preToolUse Hook の対象外**。`--allow-all` 下で秘匿情報がエージェントのコンテキストに入った状態で実行すると、secret Gist として外部化され得る。非 EMU 環境では技術的に防ぐ手段が無いため、運用ルール（実行前に `/reset-allowed-tools` で承認状態をクリアする等）で補う。
- `permissionRequest` / `notification` / `userPromptSubmitted` 等の Hook タイプは現状未使用。`--allow-all` を外して承認を自動化する運用に切り替える場合の拡張余地として記録しておく。

### sandbox の確認

Copilot CLI を再起動し、`/sandbox` の General、Auth、Filesystem、Network の各タブで状態を確認する。Copilot CLI の版によって backend 名が表示されない場合があるため、表示の有無は記録するが成功条件にはしない。Linux 系の bubblewrap 利用可否は別途記録する。user-level settings.json の配置先は、Linux 系と macOS が `~/.copilot/settings.json`、Windows が `$env:USERPROFILE\.copilot\settings.json` である。

以前の file-based managed settings 方式が残した設定の復旧は、[`troubleshooting.md`](troubleshooting.md#copilot-sandboxenabled-が意図した値にならない) を参照する。

## 監査ログ

用途別に 3 ファイル。`COPILOT_AUDIT_DIR` で出力先を変更できる。

| ファイル | 記録内容 | 書込元 |
|---|---|---|
| `~/.copilot/audit.jsonl` | ツール実行成功履歴 | `postToolUse` → `audit-log.py` |
| `~/.copilot/audit-denies.jsonl` | `copilot-guard.py` が deny 判定した呼び出し（env/blocked-files/secrets 等）| `preToolUse` → `copilot-guard.py` |
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

- [GitHub Copilot CLI — Allowing and denying tool use](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/allowing-tools)
- [GitHub Copilot CLI — Using hooks](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-hooks)
