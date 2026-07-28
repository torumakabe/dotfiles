# ADR-023: chezmoi の ps1 実行系を固定しプロファイルを読ませない

## Status

Accepted

## Context

Windows の `chezmoi update` が `Unable to find type [Microsoft.PowerShell.PSConsoleReadLine]` を 2 回出力した。経路は 3 段である。

1. chezmoi は Windows で `.ps1` を既定の実行系 `pwsh -NoLogo -File` で実行する。`-NoProfile` が無いため、スクリプト実行のたびにユーザープロファイルが読まれる。
2. プロファイルの `mise activate pwsh` が CommandNotFound ハンドラを登録し、ハンドラ本体は `[Microsoft.PowerShell.PSConsoleReadLine]::GetHistoryItems()` を参照する。
3. 非対話 pwsh には PSReadLine が読み込まれていないため、スクリプト内でコマンド解決に失敗するたびに InvalidOperation が出る。

今回の発火点は `run_onchange_after_15-mise-sync-tools.ps1` の `Get-Command -Name 'corepack'`（corepack は ADR-022 で廃止済み）だが、これは症状の一例にすぎない。スクリプトが未導入コマンドの有無を調べる限り再発する。再現は `pwsh -NoLogo -Command "Get-Command -CommandType Application -Name 'nonexistent-xyz.exe' -EA SilentlyContinue"` で取れる。

加えてプロファイルの読み込みは、chezmoi のスクリプト実行にユーザー環境の副作用（alias、関数、PATH 改変、mise の shim 差し込み）を持ち込む。スクリプトはプロファイルに依存しない前提で書かれており、読む必然性がない。

## Decision

`home/.chezmoi.toml.tmpl` の `[interpreters.ps1]` で実行系を固定し、`-NoProfile` を必ず渡す。

```toml
[interpreters.ps1]
command = "pwsh"
args = ["-NoLogo", "-NoProfile", "-File"]
```

プロファイル由来の副作用を排除し、スクリプトの実行環境を Machine+User の PATH に揃える。

## Consequences

- chezmoi のスクリプトはプロファイルに依存できなくなる。mise の shim は PATH に永続登録されているため mise 管理ツール（mise.exe / gh.exe / uv.exe / git.exe）の解決は確認済みだが、プロファイル経由でしか PATH に入らないツールは解決できない。
- 設定変更であるため、反映には `chezmoi init` の再実行が必要になる。
- 塞げるのは chezmoi 経由の実行だけで、他のツールが `pwsh -File` でスクリプトを起動する場合は mise のハンドラ問題が依然として発火する（ADR-022 の「引き継ぐ検証」）。

## 検証

- `tests/test_chezmoi_config_template.py` にソース形状と `chezmoi execute-template --init` のレンダリング結果の両方を検査するテストを追加した（`test_ps1_interpreter_is_pinned_without_the_profile` / `test_ps1_interpreter_skips_the_profile`）。
- レンダリングした config で `chezmoi --config <cfg> dump-config` を実行し、`interpreters.ps1.args` が `["-NoLogo","-NoProfile","-File"]` になることを確認した。
- クリーンな PATH（Machine+User のみ）で `pwsh -NoLogo -NoProfile -File` を実行し、mise.exe / gh.exe / uv.exe / git.exe が解決すること、未導入コマンドを引いても PSReadLine エラーが出ないことを確認した。
