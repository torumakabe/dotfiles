# ADR-032: 独自 updater で更新する WinGet パッケージを blocking pin で保護する

## Status

Accepted

Windows の mise 更新と `jdx.mise` の pin 方針だけは [ADR-040](040-windows-mise-standalone-install.md) が置換する。CopilotApp、Copilot、Rustup の blocking pin 方針は引き続き有効とする。

## Context

Windows では DSC が導入した WinGet パッケージを `winget upgrade --all` と独自 updater の双方が更新し得る。同じ実体の二重更新を避けつつ、一括更新は維持したい。

当初は mise も独自 updater の対象とし、登録版と実体版の一時的不一致を許容した。Windows の mise は ADR-040 により直接導入へ変更し、WinGet との二重管理を解消する。

## Decision

- DSC は導入と存在保証を担当し、運用手順が同じ実体へ独自 updater を正式採用する WinGet 検出対象には blocking pin を設定する。
- 対象は `GitHub.CopilotApp`、`GitHub.Copilot`、`Rustlang.Rustup` とする。`jdx.mise` は ADR-040 により対象から外す。
- `Microsoft.Azd` は `azd update` が WinGet へ委譲するため除外する。PowerToys、draw.io、Azure CLI、chezmoi も独自 updater を正式採用していないため除外する。
- `winget upgrade --all` は維持するが、リポジトリ管理外パッケージの結果は保証しない。
- mise の日常更新は全環境で `mise-self-update` に一本化し、`mise-self-upgrade` は廃止する。追加引数は受け付けない。全 OS で `mise self-update --yes --no-plugins` と成功後の `mise reshim` を実行し、mise 用 GitHub token が未設定なら `GH_TOKEN` または認証済みの `gh auth token` を `MISE_GITHUB_TOKEN` として self-update のプロセスだけへ渡す。
- Windows の mise 本体更新と直接導入への移行は ADR-040 に従う。
- その他の対象の修復では、blocking pin を上書きする `--force` の現行 WinGet 契約を使う。
- pin 撤回時は `Pinned=false` を一度配布して既存端末から削除し、その後にエントリを消す。
- この対策は Windows/WinGet 限定とする。Linux/WSL は現行の同一実体管理では追加対策せず、パッケージ管理や配置が重複する場合に管理情報と PATH 選択を再評価する。

## Consequences

- 一括更新を残したまま、正式な独自 updater と WinGet の更新競合を防げる。
- mise 本体の更新操作が全環境で共通になり、Windows 固有の `mise-self-upgrade` と専用契約が不要になる。
- 本決定は ADR-030 を置換する。Windows の mise に関する旧判断だけは ADR-040 が置換し、他のパッケージの blocking pin 方針は維持する。
- macOS は後続課題として Homebrew 登録版・実体版・PATH、自己更新後の不整合、`brew upgrade` の置換を棚卸しし、対象ごとに独自 updater 優先、Homebrew 統一、導入方法変更を判断する。Windows の pin を転用できるとは仮定せず、決定を必要な ADR、operations、関連文書、契約テストへ反映する。
