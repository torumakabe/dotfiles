# ADR-030: mise 本体の self-update と self-upgrade を使い分ける

## Status

Accepted

## Context

mise 本体の更新には、mise 組み込みの `self-update` と、OS ごとの導入元が推奨する更新手段がある。導入後の利用者向け操作として、全プラットフォームで本体だけを更新する操作と、導入元の管理記録を維持する操作を分ける必要がある。

`mise self-update` は既定でプラグインも更新する。また、Windows では WinGet/DSC の記録と実ファイルの版が一時的に異なる可能性がある。ADR-028 は bootstrap で既存導入を置換しない判断であり、本 ADR は導入後の更新操作を対象とする。

## Decision

- `mise-self-update` は全環境で `mise self-update --yes --no-plugins` を実行し、成功後に `mise reshim` を実行する。mise 用の GitHub token が未設定なら、`GH_TOKEN` または認証済みの `gh auth token` を `MISE_GITHUB_TOKEN` として self-update のプロセスだけへ渡す。追加引数は受け付けない。
- `mise-self-upgrade` は各環境の通常推奨手段を使う。
- Windows では `winget upgrade --id jdx.mise --source winget --disable-interactivity --force` を実行し、実行中の mise プロセスを確認する。成功後は `mise reshim` を実行する。
- macOS、Linux、WSL では `mise-self-update` へ委譲する。Homebrew などの導入元を自動検出して更新する処理は追加しない。
- Windows で導入元の管理記録と実ファイルの版を一致させて更新・修復したい場合は、`mise-self-upgrade` を使う。

## Consequences

全環境で `mise-self-update` によりプラグインを変更せず、本体だけを同じ手順で更新できる。macOS、Linux、WSL では既存の導入元を問わず、利用者が選択した導入方法を維持できる。

Windows では `mise-self-update` を使うと WinGet/DSC の記録と実ファイルの版が一時的に異なり得るため、管理記録の整合性が必要な場合は `mise-self-upgrade` を選ぶ。OS ごとの更新手段の差異と、更新後の reshim が利用者向けコマンドの契約になる。
