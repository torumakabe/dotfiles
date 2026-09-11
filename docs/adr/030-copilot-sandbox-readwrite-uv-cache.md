# ADR-030: Copilot sandbox の uv は専用 cache を使う

## Status

Accepted

## Context

Copilot runtimeは通常のuv cacheをread-onlyで許可するが、`uv run`、`uv sync`、`uv pip`もcache内へ一時ファイルとlockを作成する。同じpathを利用者設定の`readwritePaths`へ追加してもruntimeのread-only grantは残る。

Windows sandboxは`LOCALAPPDATA`をAppContainer配下へ変更するため、hostの既定cacheだけを許可してもuvの参照先と一致しない。uvが公式に提供する`UV_CACHE_DIR`とpreToolUse hookのcommand変更を組み合わせる必要がある。

## Decision

preToolUse hookは`node-global-enforcer.py`、`copilot-guard.py`、`uv-enforcer.py`の順で実行する。前二つは変更前のcommandを検査し、`uv-enforcer.py`は許可したbashとPowerShellのcommandへCopilot専用`UV_CACHE_DIR`を追加する。PowerShellでは元のcommandを同じPowerShell実体の子プロセスへ渡し、終了コードをtool callへ返す。

専用cacheはmacOSで`~/Library/Caches/github-copilot/uv`、Linux系で`${XDG_CACHE_HOME:-~/.cache}/github-copilot/uv`、Windowsで`%LOCALAPPDATA%\GitHubCopilot\uv`とする。設定同期は対象directoryを作成してから、そのpathだけを`readwritePaths`へ追加する。

既存のread-onlyまたはdeny設定が同じpathか親directoryを指す場合と、管理対象がsymbolic linkまたはreparse pointの場合は設定変更前に停止する。hostのuv cache、cache home全体、mise data rootにはwrite grantを与えない。

## Consequences

- sandbox shellから起動したuvは専用cacheへ必要な一時ファイルとlockを書き込める。
- command内で間接的にuvを起動した場合も同じcacheを使う。PowerShellは子プロセスを一つ追加で起動する。
- command hook自体はsandbox外で動作するため、hostのuv cacheを使う。
- 実測結果と未確認環境は[実機検証記録](../copilot-sandbox-verification.md#検証記録)で管理する。
- 撤去条件と対象範囲は[ワークアラウンド一覧](../../.github/copilot-instructions.md#ワークアラウンド定期チェック対象)で管理する。
