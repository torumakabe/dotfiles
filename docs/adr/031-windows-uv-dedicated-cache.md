# ADR-031: Windows でも Copilot sandbox の uv 専用キャッシュを配布する

## Status

Accepted

## Context

ADR-026 は、macOS と Linux（WSL を含む）だけで uv コマンド専用キャッシュを配布し、Windows には hook の書き換えと `readwritePaths` 追加を行わなかった。その後の実機検証で、Windows sandbox は `%LOCALAPPDATA%`、`%TEMP%`、`%TMP%` を隔離先へ再配置し、ホスト既定の uv キャッシュ書き込みは拒否する一方、ホストで解決した `%LOCALAPPDATA%\github-copilot\uv` を `readwritePaths` に追加すると書き込みが成功することを確認した。PowerShell の `preToolUse` hook でコマンド単位の `UV_CACHE_DIR` 前置も実 CLI で機能した。`mise activate pwsh` 済みの通常シェルでは `uv` が実体バイナリへ解決されるため、shim 起因の別問題は今回の変更対象に含めない。`%TEMP%` / `%TMP%` の全面的な切替も uv 実行の必須条件ではないため扱わない。ADR-026 の他の判断は置換しない。

## Decision

Windows でも、Copilot CLI の許可済み PowerShell tool コマンドだけに `UV_CACHE_DIR` を前置し、専用キャッシュ `%LOCALAPPDATA%\github-copilot\uv` を使わせる。設定同期は同じ絶対パスを作成し、既存の `readwritePaths`、`readonlyPaths`、`deniedPaths` と安全に整合する場合だけ `readwritePaths` へ追加する。`LOCALAPPDATA` が unsafe な形式、非ディレクトリ、ドライブルート、symlink、junction などの reparse point を含む場合や、既存の restrictive rule と衝突する場合は拒否する。POSIX の挙動、shim 起因の課題、`TEMP` / `TMP` の扱いは変更しない。

## Consequences

- Windows でも、通常シェルの uv 設定を変えずに sandbox 内の uv キャッシュをホストへ永続化できる。
- hook と設定同期が同じ絶対パス検証を共有する必要があるため、両実装とテストを同時に保守する。
- Windows の shim 問題や一時ディレクトリ全体の再配置は残るため、必要になれば別の判断として扱う。
