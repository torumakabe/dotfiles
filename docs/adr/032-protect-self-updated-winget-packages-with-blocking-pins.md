# ADR-032: 独自 updater で更新する WinGet パッケージを blocking pin で保護する

## Status

Accepted

## Context

Windows では DSC が導入した WinGet パッケージを `winget upgrade --all` と独自 updater の双方が更新し得る。同じ実体の二重更新を避けつつ、一括更新は維持したい。

WinGet v1.29.380（ja-JP）では、`GitHub.Copilot` の blocking pin が通常更新を止め、`--force` で 1.0.85 から 1.0.86 へ更新でき、`copilot update` も現在・最新 1.0.86、終了 0 となることを確認した。Windows では `jdx.mise` の WinGet pin を Blocking のまま、`mise self-update --yes --no-plugins` が実体を 2026.9.10 から 2026.9.11 へ更新し、続く `mise reshim` も成功した一方、WinGet 登録版は 2026.9.5 のままだった。これは日常更新を全 OS で `mise self-update` に統一し、Windows の登録版と実体版の一時的不一致を許容する本決定を直接裏付ける。`winget pin list --id ... --exact` は全 pin を返すため、確認には一覧行の ID 完全一致が必要である。

## Decision

- DSC は導入と存在保証を担当し、運用手順が同じ実体へ独自 updater を正式採用する WinGet 検出対象には blocking pin を設定する。
- 対象は `GitHub.CopilotApp`、`GitHub.Copilot`、`jdx.mise`、`Rustlang.Rustup` とする。
- `Microsoft.Azd` は `azd update` が WinGet へ委譲するため除外する。PowerToys、draw.io、Azure CLI、chezmoi も独自 updater を正式採用していないため除外する。
- `winget upgrade --all` は維持するが、リポジトリ管理外パッケージの結果は保証しない。
- `jdx.mise` の日常更新は全環境で `mise-self-update` に一本化し、`mise-self-upgrade` は廃止する。`mise-self-update` は追加引数を受け付けず、`mise self-update --yes --no-plugins` と成功後の `mise reshim` を実行し、mise 用 GitHub token が未設定なら `GH_TOKEN` または認証済みの `gh auth token` を `MISE_GITHUB_TOKEN` として self-update のプロセスだけへ渡す。
- Windows では WinGet/DSC の登録版と実体版の一時的不一致を許容する。再導入や登録修復が必要な場合だけ、`winget upgrade --id jdx.mise --exact --source winget --force` または同等の `winget install` を手動実行し、日常用の公開関数にはしない。
- その他の対象の修復では、blocking pin を上書きする `--force` の現行 WinGet 契約を使う。
- pin 撤回時は `Pinned=false` を一度配布して既存端末から削除し、その後にエントリを消す。
- この対策は Windows/WinGet 限定とする。Linux/WSL は現行の同一実体管理では追加対策せず、パッケージ管理や配置が重複する場合に管理情報と PATH 選択を再評価する。

## Consequences

- 一括更新を残したまま、正式な独自 updater と WinGet の更新競合を防げる。
- mise 本体の更新操作が全環境で共通になり、Windows 固有の `mise-self-upgrade` と専用契約が不要になる。
- `jdx.mise` の登録版と実体版は一時的に異なり得るが、通常運用から WinGet 修復を分離できる。本決定は ADR-030 を置換する。
- macOS は後続課題として Homebrew 登録版・実体版・PATH、自己更新後の不整合、`brew upgrade` の置換を棚卸しし、対象ごとに独自 updater 優先、Homebrew 統一、導入方法変更を判断する。Windows の pin を転用できるとは仮定せず、決定を必要な ADR、operations、関連文書、契約テストへ反映する。
