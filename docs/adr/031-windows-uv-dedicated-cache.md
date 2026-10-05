# ADR-031: Windows でも Copilot sandbox の uv 専用キャッシュを配布する

## Status

Deprecated

## Context

ADR-026 は、macOS と Linux（WSL を含む）だけで uv コマンド専用キャッシュを配布し、Windows には hook の書き換えと `readwritePaths` 追加を行わなかった。その後の実機検証で、Windows sandbox は `%LOCALAPPDATA%`、`%TEMP%`、`%TMP%` を隔離先へ再配置し、ホスト既定の uv キャッシュ書き込みは拒否する一方、ホストで解決した `%LOCALAPPDATA%\github-copilot\uv` を `readwritePaths` に追加すると書き込みが成功することを確認した。PowerShell の `preToolUse` hook でコマンド単位の `UV_CACHE_DIR` 前置も実 CLI で機能した。`mise activate pwsh` 済みの通常シェルでは `uv` が実体バイナリへ解決されるため、shim 起因の別問題は今回の変更対象に含めない。`%TEMP%` / `%TMP%` の全面的な切替も uv 実行の必須条件ではないため扱わない。ADR-026 の他の判断は置換しない。

Copilot CLI 1.0.92-4 以降が uv の既定キャッシュへ自動的に read-write grant を与えるようになり、本 ADR の専用キャッシュは不要になった。後継の Windows 固有判断はなく、共通方針は更新後の ADR-026 に記録するため、本 ADR を廃止する。

## Decision

当時は Windows でも、Copilot CLI の許可済み PowerShell tool コマンドだけに `UV_CACHE_DIR` を前置し、専用キャッシュ `%LOCALAPPDATA%\github-copilot\uv` を使わせると決定した。設定同期は同じ絶対パスを作成し、既存の `readwritePaths`、`readonlyPaths`、`deniedPaths` と安全に整合する場合だけ `readwritePaths` へ追加した。`LOCALAPPDATA` が unsafe な形式、非ディレクトリ、ドライブルート、symlink、junction などの reparse point を含む場合や、既存の restrictive rule と衝突する場合は拒否した。POSIX の挙動、shim 起因の課題、`TEMP` / `TMP` の扱いは変更しなかった。

## Consequences

- 専用キャッシュ、`UV_CACHE_DIR` 書き換え、専用 `readwritePaths` は撤去済みである。
- 移行時は旧専用キャッシュと完全一致する entry だけを除去し、利用者所有の他の grant は保持する。
- Windows 固有の後継判断は設けず、Copilot CLI の既定動作を POSIX と共通利用する。
