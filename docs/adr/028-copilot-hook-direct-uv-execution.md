# ADR-028: Copilot は mise 管理ツールを実体パスから実行する

## Status

Accepted

## Context

Copilot CLI のコマンドフックは親プロセスの環境を継承する。従来の `MISE_ENABLE_TOOLS=uv mise exec -- uv run ...` はフックごとに mise と設定を読み込み、親の `PATH` から mise を実行できることを前提としていた。

変更前の WSL では、共有 profile 単独で install path 30 件、shim 0 件だった一方、対話 zsh の activation を継承した Copilot CLI では検証対象43件がすべて shim 経由で解決された。これは修正前の観測であり、現在のエンドツーエンド動作を示すものではない。

共有 mise config は `activate_shims = false` を設定する。実際の mise 管理 node を使う隔離したオフライン動作試験では、`activate_shims = true` の負の対照は一時 shim ディレクトリを残し、`false` は除去した。どちらも導入済み node の実体へ解決した。

mise 2026.9.4 の直接試験では、`mise env` 適用後と activation 後はいずれも install path 30 件、全件一意だった。render 済み設定、初期 `PATH` に `~/.local/bin` なし、`activate_shims = false` の macOS 試験では、mise install path が先頭、`uv` は 0.12.10 の実体、install path 30 件、shim 0 件となった。

現在の macOS には古い `~/.local/bin/uv` 0.9.17 があり、mise 管理版は 0.12.10 である。これは設計の性質ではなく、配布時に確認する衝突である。

## Decision

mise はツールの導入、バージョン固定、更新を担い、共有 config の `activate_shims = false` を維持する。zsh の `mise activate zsh` と PowerShell の `mise activate pwsh` は維持する。

Copilot のコマンドフック5件（`preToolUse` 3件、`postToolUse`、`postToolUseFailure`）は bash と PowerShell の双方で、親プロセスの `PATH` から解決した `uv run ...` を直接起動する。`MISE_ENABLE_TOOLS=uv` は実体の uv には作用せず、フックの子プロセスへ不要に漏れるため削除する。

Windows の永続的な User `PATH` には、非対話互換性のため mise shims を残す。このため Windows の実体パス契約は現時点で、PowerShell profile が `mise activate pwsh` を実行したターミナルから Copilot CLI を起動することを要件とする。GUI または profile を読まない起動は未検証であり、対応済みとはしない。

古い `~/.local/bin/uv` は自動削除せず、配布時に実体の解決先とバージョンを確認する。

## Consequences

- フックごとの mise 起動と設定読み込みがなくなり、実行契約は親プロセスが提供する uv の実体パスになる。
- 動作試験は shim の有無だけでなく、オフラインの実ツール解決を正負両条件で検証する。
- Windows と WSL の直接実行フックはエンドツーエンド未検証である。Windows の GUI／非 profile 起動と macOS の既存 uv 衝突も、配布時の確認事項として残る。
