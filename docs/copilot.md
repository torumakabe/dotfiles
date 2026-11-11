# GitHub Copilot Guide

このリポジトリは、自身の作業用設定と、chezmoi で開発環境へ配布する設定を区別して管理する。GitHub Copilot 製品の一般的な使い方や `/plugin` の詳細は公式ドキュメントを参照。

## GitHub Copilot harness と GitHub Copilot CLI

**GitHub Copilot harness** は、GitHub Copilot CLI、GitHub Copilot app、VS Code が共有する agent runtime である（[Agent harnesses](https://code.visualstudio.com/docs/agents/concepts/agent-harnesses)）。ただし公式文書は、runtime の共有がツール、権限、設定の同一性を意味しないと明記している。このため、このリポジトリは公式文書で製品間の共通読み込みを確認できた項目だけを GitHub Copilot harness 共通の設定として扱う。

- **GitHub Copilot harness 共通**：`~/.copilot/` 配下のカスタム指示（`copilot-instructions.md`、`instructions/`）、`mcp-config.json`、`skills/`、`hooks/`
- **GitHub Copilot CLI 固有**：CLI 本体の導入と更新、`settings.json`（sandbox、権限モード、プラグイン、実験機能）、`lsp-config.json`、`installed-plugins/`

sandbox の設定は GitHub Copilot app と GitHub Copilot CLI で別々に管理され、一方の変更は他方に反映されない（[Configuring local sandbox settings](https://docs.github.com/en/copilot/how-tos/cloud-and-local-sandboxes/configuring-local-sandbox-settings)）。このリポジトリが同期するのは GitHub Copilot CLI の設定であり、GitHub Copilot app と VS Code の sandbox 設定は扱わない。

## 管理対象

### カスタム指示とエージェント

| 管理元 | 適用範囲と読み込み |
| --- | --- |
| [`.github/copilot-instructions.md`](../.github/copilot-instructions.md) | このリポジトリでの作業に適用する。開発環境への配布対象ではない |
| [`.github/agents/manage-adr.agent.md`](../.github/agents/manage-adr.agent.md)、[`.github/agents/review-repo.agent.md`](../.github/agents/review-repo.agent.md) | このリポジトリで選択して使うカスタムエージェント。ユーザー共通のエージェントとしては配布しない |
| [`home/private_dot_copilot/copilot-instructions.md`](../home/private_dot_copilot/copilot-instructions.md) | `~/.copilot/copilot-instructions.md` へ配布し、他のリポジトリでもユーザーレベルの指示として GitHub Copilot harness が読み込む |

`home/` にソースがあるだけではユーザーレベルの指示として読み込まれない。リポジトリ用の指示から共通規範を参照するときは、配布済みであることを前提にせずソースを参照する。

配布用のカスタムエージェントと skill は管理しない。外部 skill の管理は[プラグインとスキル](#プラグインとスキル)を参照する。

### その他の配布設定

`~/.copilot/` 配下のうち、次の設定も chezmoi で管理する。

- `mcp-config.json`：手動 MCP サーバー設定。GitHub Copilot harness 共通（`/mcp add` 後は `chezmoi re-add`）
- `settings.json` の実験機能、プラグイン、sandbox 設定、`defaultPermissionMode`、`assistedApprovalInstructions`：GitHub Copilot CLI 固有。POSIX と Windows の `run_after_35-configure-copilot-sandbox` で既存設定へマージ

`installed-plugins/` と `plugin-data/` は GitHub Copilot CLI が管理し、chezmoi の対象外とする。

共通設定で `defaultPermissionMode` を `assisted` に指定し、`assistedApprovalInstructions` に承認判断への追加指示を定義する。

設定ファイルの値と構造の検証は GitHub Copilot CLI に任せ、設定値を期待値として固定するテストは追加しない。リポジトリのテストでは、設定同期スクリプトの既存値の保持や移行処理を確認する。

通常の shell tool が `uv run` を使えるよう、uv managed Python の保存先を読み取り専用で許可する。Python の事前準備と設定同期は [`operations.md`](operations.md#sandbox-内の-uv-managed-python)、実機での確認は[検証手順](copilot-sandbox-verification.md#実-cli-で-uv-と-sandbox-設定を確認する)を参照する。

## CLI 本体の導入元

| 環境 | 導入元 |
|------|--------|
| Linux / WSL / Codespaces / Dev Container | 固定した公式リリースアーカイブを SHA-256 検証（[`docs/operations.md`](operations.md#bootstrap--shell-pin-の更新)） |
| macOS | 固定した公式リリースアーカイブを SHA-256 検証 |
| Windows | `winget` (`reference/windows/configuration.dsc.yaml`) |

更新は全 OS で `copilot update`。

macOS では `home/run_once_before_15-install-copilot-cli.sh.tmpl` が `~/.local/bin/copilot` を配置し、既存の Homebrew formula 版を削除する。公式バイナリの配置と実行確認が完了するまでは formula を削除しない（[ADR-033](adr/033-manage-azd-and-copilot-cli-via-official-os-channels.md)）。

Codespaces / Dev Container のベースイメージには `/usr/local/bin/copilot` が同梱されていることがあり、`copilot update` の対象外のまま古くなる。このため導入判定は `command -v copilot` ではなく `~/.local/bin/copilot` の実体で行う（[`docs/troubleshooting.md`](troubleshooting.md#codespaces--dev-container-で-copilot-のバージョンが古い)）。

## LSP サーバー

GitHub Copilot CLI の LSP サーバーは `~/.copilot/lsp-config.json` (chezmoi 管理) で設定する。Python 向け `ty` (Astral) は mise バックエンドがないため `uv tool install ty`（`run_once` で自動化）、TypeScript 等の npm パッケージは mise の `npm:` バックエンドで管理する。

## プラグインとスキル

プラグインのマーケットプレース登録と有効化は [`home/.chezmoitemplates/copilot-user-settings.json`](../home/.chezmoitemplates/copilot-user-settings.json) を管理元とし、既存の `settings.json` へマージする。`github/awesome-copilot` の `azure-cost-health-check`、`ai-credits-breakdown` と、`torumakabe/copilot-agent-plugins` の `personal-skills`、`skill-creator` を有効にする。登録外の既存プラグインも保持するため、排他的な許可リストではない。GitHub Copilot CLI がプラグイン本体の導入とセッション開始時の更新を担当し、スキル本文の管理元は提供元にある。

外部 skill はプラグインまたは `gh skill` で管理し、このリポジトリへ複製しない。

```bash
# GitHub Copilot の user scope へ外部 skill を導入する
gh skill install <owner>/<repo> <skill-name> --agent github-copilot --scope user
```

`personal-skills@torumakabe-agent-plugins` は `agentfinder`、`japanese-technical-writing`、`lsp-setup` を提供する。利用時はスキル名を指定する。`agentfinder` が返した候補は、ユーザーが明示的に選ぶまで自動インストールしない。

`gh-stack` は Stacked PR の設計と `gh stack` の非対話操作を GitHub Copilot に教える公式 skill である。セットアップスクリプトは、公式 skill と対応する GitHub CLI extension が未導入の場合だけ `github/gh-stack` から取得する。提案条件は[配布用カスタム指示](../home/private_dot_copilot/copilot-instructions.md#エージェント行動規範)、操作方法は公式 skill を参照する。管理境界は [ADR-024](adr/024-gh-stack-distribution-and-updates.md)、更新手順は [operations.md](operations.md#gh-stack-の更新) を参照する。

## GitHub Copilot フック

このリポジトリは GitHub Copilot の command hook を配布しない。既存端末からの削除と保持するデータは[移行手順](operations.md#github-copilot-フック廃止時の移行)、廃止の判断は [ADR-041](adr/041-copilot-hooks-retirement.md) を参照する。Git の gitleaks pre-commit フックは配布する。

## GitHub Copilot CLI local sandbox

設計上の前提と限界:

- `sandbox.credentials.envVars` は `AZURE_CLIENT_SECRET`、`ARM_CLIENT_SECRET`、`ARM_ACCESS_KEY`、`AZURE_STORAGE_CONNECTION_STRING` を sandbox 子プロセスへ偽の値で渡し、承認した HTTPS host への request header に限って proxy が実値を注入する。設定する host は予約済みの `mask-only.invalid` であり、実際の宛先ではない。
- `sandbox.enabled=true` の session では local sandbox が shell command、ローカル MCP server、filesystem policy を対象とする。`sandboxMcpServers=true`、`sandboxLspServers=false` とし、GitHub Copilot CLI 組み込みファイルツールの filesystem policy は software-only safeguard とする。MCP sandbox の判断は [ADR-035](adr/035-copilot-cli-sandbox-mcp-servers.md) を参照する。
- 通常の shell tool が使う mise、uv managed Python の保存先と uv user config file を読み取り専用で追加する。この許可は sandbox 内のすべてのプロセスに適用される。
- 共通設定の定義元は `home/.chezmoitemplates/copilot-user-settings.json` である。`sandbox.enabled` の初回値、設定保持、組織管理設定との優先関係は [`operations.md`](operations.md#github-copilot-local-sandbox-の既定値) を参照する。
- `/share gist`（`--share-gist`）はユーザーが直接実行するコマンドである。秘匿情報がエージェントのコンテキストに入った状態で実行すると、secret Gist として外部化され得る。

### filesystem の glob 例

glob 対応版の GitHub Copilot CLI では、利用者の `settings.json` の `sandbox.userPolicy.filesystem` に次のようなパターンを指定できる。これは記述例であり、このリポジトリは拒否パスを追加しない。

```json
{
  "deniedPaths": ["/path/to/project/**/*.pem"]
}
```

実際の絶対パスへ置き換え、既存の `deniedPaths` に追加する。glob は policy 構築時に存在する一致パスへ展開されるため、その後に作成したファイルは構築済み policy に自動追加されない。

### sandbox の確認

GitHub Copilot CLI を再起動し、`/sandbox` の General、Auth、Filesystem、Network の各タブで状態を確認する。環境別の実行確認は[実機検証手順](copilot-sandbox-verification.md)、設定が意図した値にならない場合は [`troubleshooting.md`](troubleshooting.md#github-copilot-sandboxenabled-が意図した値にならない) を参照する。

## 参考

- [VS Code — Agent harnesses](https://code.visualstudio.com/docs/agents/concepts/agent-harnesses)
- [VS Code — Agent hooks](https://code.visualstudio.com/docs/copilot/customization/hooks)
- [VS Code — MCP servers](https://code.visualstudio.com/docs/copilot/customization/mcp-servers)
- [VS Code — Agent skills](https://code.visualstudio.com/docs/copilot/customization/agent-skills)
- [GitHub Copilot — Custom instructions support](https://docs.github.com/en/copilot/reference/custom-instructions-support)
- [GitHub Copilot — Configuring local sandbox settings](https://docs.github.com/en/copilot/how-tos/cloud-and-local-sandboxes/configuring-local-sandbox-settings)
- [GitHub Copilot CLI — Allowing and denying tool use](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/allowing-tools)
- [GitHub Copilot CLI — Using hooks](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-hooks)
