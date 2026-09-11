# ADR-028: Copilot は mise 管理ツールを実体パスから実行する

## Status

Accepted

## Context

Copilot CLI のコマンドフックは親プロセスの環境を継承する。従来の `MISE_ENABLE_TOOLS=uv mise exec -- uv run ...` はフックごとに mise と設定を読み込み、親の `PATH` から mise を実行できることを前提としていた。

commit c653c9a 後の WSL では、`activate_shims = false` により shim path は 0 件になったが、検証対象 43 コマンドのうち 17 件は `~/.local/bin`、`~/go/bin`、`~/.cargo/bin`、`/usr/local/bin`、`/usr/bin` にある先行 PATH エントリから解決された。`uv` は `~/.local/bin/uv` 0.9.26 へ解決され、`mise which uv` は lock 済みの実体 `uv` 0.12.10 を返した。すべての Copilot `preToolUse` フックは、0.9.26 が `~/.config/uv/uv.toml` の `system-certs=true` を解析できず、ガードスクリプトを起動する前に失敗した。

`mise hook-env --force` だけでは PATH の順序は変わらなかった。公式の一時 override `MISE_ACTIVATE_AGGRESSIVE=true` を設定し、`mise hook-env --force -s zsh` を実行すると、WSL で代表として確認した `uv`、`terraform`、`cue`、`rg` の 4 コマンドだけが期待する mise install path からの実行に成功した。shim path は 0 件のまま、mise install path 群は PATH の位置 1 以降へ移動した。この結果が示すのは一時 override 下の 4 コマンドだけであり、永続設定の配布後に 43 コマンドすべてとフックを検証する必要がある。

したがって、`activate_shims = false` は shim を除外するが、実体パスを先行させる契約を単独では満たさない。

後続の受け入れ確認では、built-in shell 内の `bash -lc` が `PATH` を再構成するため、検証 script 本体を built-in shell tool へ直接渡す必要があると判明した。この方法では 43 件中 40 件が期待する mise 実体へ解決した。残る 3 件の filesystem grant は ADR-029 で扱う。

2026-09-11 の実測（Copilot CLI 1.0.83、profile 読み込み済み PowerShell 7.6.5 の alias が選ぶ WinGet 本体 `copilot.exe` から起動し、built-in PowerShell で直接確認）では、host の mise install path 群が shims より前に並ぶ順序を sandbox が保持し、検証対象の 9 コマンドはすべて mise 実体へ解決した。同じ shell で mise や入れ子の `pwsh` を呼ばず、`uv`、`uvx`、`node`、`npm`、`npx`、`corepack`、`tsc`、`dotnet`、`jq` を直接 `--version` 実行した結果も、各 exit code 0、stderr なし、PowerShell tool 全体の exit code 0 だった。これにより現行経路では、9 コマンドが shim や mise config 解決を介さず実体から起動できることを確認した。この tool call は `preToolUse` に阻害されなかったが、フック 5 件全体の検証を意味しない。過去に観測した shim-only の解決はこの起動経路では再現せず、原因は未確定のまま残る。sandbox 内で mise 自身が global config を canonicalize できない既知の問題は残るが、built-in shell は mise や shim を起動しないためこの問題から分離できる。profile を読む子 shell、GUI または profile なしの起動はこの実測の対象外であり、引き続き未検証である。

## Decision

mise はツールの導入、バージョン固定、更新を担う。共有 global config は `activate_shims = false` と `activate_aggressive = true` を設定する。前者は shim farm を除外し、後者は activation と hook 実行時に mise install path を OS や他のパッケージ管理ツールのディレクトリより前へ置く。競合する実体は自動削除しない。

zsh の公式 `mise activate zsh` と PowerShell の公式 `mise activate pwsh` を維持する。Unix の共有 profile では、継承環境と非対話 shell のために公式 `mise env` を維持する。OS や他のパッケージ管理ツールのディレクトリが mise install path より前に置かれ得るため、aggressive activation を実体パス契約の必須条件とする。

Copilot のコマンドフック 5 件（`preToolUse` 3 件、`postToolUse`、`postToolUseFailure`）は bash と PowerShell の双方で、親プロセスの `PATH` から実体の `uv` を解決し、プレーンな `uv run ...` を直接起動する。フック内では mise を起動せず、`MISE_ENABLE_TOOLS=uv` も設定しない。

Windows の永続的な User `PATH` には、非対話互換性のため mise shims を残す。このため Windows の実体パス契約は現時点で、PowerShell profile が `mise activate pwsh` を実行したターミナルから Copilot CLI を起動することを要件とする。GUI または profile を読まない起動は未検証であり、対応済みとはしない。

受け入れ確認では検証 script 本体を built-in shell tool へ直接渡す。`bash -lc`、`bash -c`、`sh -c`、`env -i` などで起動時の request env を変更した結果は、実体パス契約の判定に使わない。

## Consequences

- activation と hook は shim を追加せず、aggressive 設定により mise install path を既存 PATH の競合より前に置く。フックごとの mise 起動と設定読み込みはなくなり、実行契約は親プロセスが提供する `uv` の実体パスになる。
- WSL の built-in shell 直接検証では 43 件中 40 件が実体パス契約を満たした。sandbox 内で symlink target を解決できない残り 3 件は、PATH 順序やフック方式ではなく ADR-029 の filesystem grant で解決し、設定配布後に再検証する。Copilot フックのエンドツーエンド検証も残る。
- Windows は、profile 読み込み済み PowerShell から WinGet 本体を起動する経路に限り、host の mise 実体 PATH 順序を sandbox が保持し、9 コマンドを shim や mise config 解決を介さず実体から実行できることを 2026-09-11 に確認した。sandbox 内で mise 自身が config を canonicalize できない問題、profile を読む子 shell、GUI または profile なしの起動、Copilot フック 5 件全体のエンドツーエンド検証は残る。
