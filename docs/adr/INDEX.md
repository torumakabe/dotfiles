# Architecture Decision Records

このリポジトリの永続的な設計判断を記録する。運用ノート（`docs/architecture.md` 等）とは分離し、「6ヶ月後になぜこうなっているか聞かれそうな判断」のみを ADR にする。

## 原則

- 1 ADR = 30 行以下を目安
- セクションは **Status / Context / Decision / Consequences** の 4 つ
- Status は `Proposed` / `Accepted` / `Deprecated` / `Superseded by ADR-NNN` のいずれか
- 作成・廃止・置換・レビューは `manage-adr` エージェントで管理する

## 一覧

| # | タイトル | Status |
| --- | --- | --- |
| [001](001-path-centralized-in-profile.md) | PATH 管理を ~/.profile に集約する | Accepted |
| [002](002-mise-shims-symlink-to-local-bin.md) | mise shim を ~/.local/bin に symlink する | Accepted |
| [003](003-mise-shim-exclude-pattern.md) | mise shim symlink は除外パターン方式にする | Accepted |
| [004](004-azd-and-copilot-cli-outside-mise.md) | azd と copilot-cli を mise 外で管理する | Accepted |
| [005](005-no-github-token-in-shell-env.md) | GITHUB_TOKEN を環境変数に常駐させない | Accepted |
| [006](006-pretooluse-hook-no-allow.md) | Copilot CLI preToolUse フックは allow を出力しない | Accepted |
| [007](007-python-with-uv-and-pep723.md) | Python スクリプトは uv run + PEP 723 で実行する | Accepted |
| [008](008-zshenv-sources-profile.md) | ~/.zshenv は ~/.profile を source する | Accepted |
| [009](009-mise-rust-windows-isolate-home.md) | Windows では mise の rust home を外部 rustup から分離する | Accepted |
| [010](010-url-allowlist-via-pretooluse-hook.md) | Copilot CLI の URL 包括制御は preToolUse Hook で行う | Superseded by ADR-015 |
| [011](011-edit-windows-via-winget-dsc.md) | Microsoft Edit は Windows のみ winget/DSC で管理する | Accepted |
| [012](012-wsl-op-ssh-sign-crlf-wrapper.md) | WSL では op-ssh-sign-wsl.exe を CR 除去ラッパー経由で呼ぶ | Accepted |
| [013](013-mise-lockfile-sync-hook.md) | mise lockfile 変更時に install / reshim を自動同期する | Accepted |
| [014](014-github-multi-account-https-auth-per-owner.md) | GitHub 多アカウント HTTPS 認証は credential の URL パス方式 + gh auth token --user で解決する | Accepted |
| [015](015-copilot-cli-shell-network-via-local-sandbox.md) | Copilot CLI shell のネットワーク制御は local sandbox で行う | Accepted |

## テンプレート

新規 ADR は次の雛形に従う:

```markdown
# ADR-NNN: <判断のタイトル>

## Status

Accepted

## Context

<背景・問題・制約。なぜこの判断が必要だったか>

## Decision

<採用した判断。能動態で簡潔に>

## Consequences

<結果として得られるもの・失うもの・今後のリスク>
```
