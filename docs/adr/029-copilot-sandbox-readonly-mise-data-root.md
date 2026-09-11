# ADR-029: Copilot sandbox は mise data root を read-only grant する

## Status

Accepted

## Context

Copilot runtime cli-1.0.83 は統合した `PATH` を MXC request env へ渡し、MXC は ambient env を消した後に request env を再設定する。`allowDevToolAccess` は `PATH` を変更せず、filesystem grant を生成する。built-in shell へ直接渡した検証では 43 件中 40 件が成功したが、`corepack`、`npx`、`tsc` は host に存在しても sandbox 内で symlink target を解決できなかった。

PATH bin の自動 read grant は、mise data root 内の別 directory を指す symlink target を許可しない。さらに `core:dotnet` は既定の `installs` 外にある `dotnet-root` を使うため、`installs` だけでは全 mise 管理ツールを対象にできない。

Windows sandbox では `LOCALAPPDATA` が package sandbox 配下へリダイレクトされ、`MISE_DATA_DIR` と `MISE_INSTALLS_DIR` も継承されないことを確認した。このため、sandbox 内の環境変数から host の mise directory を再算出することはできず、設定同期時に sandbox 外で grant 対象を確定する必要がある。

## Decision

sandbox はこの問題の回避目的で無効にせず、設定同期時に host の環境から mise data root を算出し、`sandbox.userPolicy.filesystem.readonlyPaths` へ追加する。data root は `MISE_DATA_DIR` を最優先し、未設定時は `XDG_DATA_HOME`、Windows の `LOCALAPPDATA`、最後に OS ごとの `HOME` fallback（Unix は `~/.local/share`、Windows は `~/AppData/Local`）から `mise` directory を算出する。

`MISE_INSTALLS_DIR` が data root 外を指す場合は、その directory も read-only で追加する。対象 directory は policy の設定前に作成し、存在しない path による sandbox 起動失敗を防ぐ。既存 entry を保持して重複なく追加し、write grant は与えない。

管理対象 path が既存の `readwritePaths` に既にあれば、その write grant を維持し `readonlyPaths` へは追加しない。既存の `deniedPaths` にあれば拒否設定を上書きせず、settings を書き換える前に明示エラーで停止する。比較は POSIX 側で末尾 slash を正規化した文字列一致、PowerShell 側で `GetFullPath` と `OrdinalIgnoreCase` を用いる。

## Consequences

- mise backend が data root 内で共有する実体や symlink target と、data root 外へ明示した installs directory を sandbox 内から読み取れる。
- read 範囲は個別の tool directory ではなく mise data root 全体へ広がるが、書き込み権限は増えない。
- 既存の `readwritePaths` や `deniedPaths` と衝突する場合は自動的な上書きをせず、write grant の維持または明示エラーによる停止を優先するため、既存設定の意図しない緩和や拒否解除を防ぐ。
- `readonlyPaths` は既存 entry を保持して追加するため、mise data root の移動後も旧 entry は自動判別して削除されず残る。移動時は設定を再同期し、旧 managed path を確認して手動で除去する。
- mise の directory 規則や sandbox policy schema が変わった場合は、算出方法と起動前作成の前提を再検証する。
