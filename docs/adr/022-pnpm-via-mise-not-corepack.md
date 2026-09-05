# ADR-022: pnpm は corepack ではなく mise で直接管理する

## Status

Deprecated

pnpm の mise 管理を撤去したため廃止。導入方針は [ADR-028](028-remove-mise-use-official-per-tool-install-paths.md) を参照。

## Context

`home/dot_config/mise/config.toml.tmpl` が管理していた Node 関連ツールは `node = "lts"` のみで、pnpm / yarn は node に同梱される corepack を `run_onchange_after_15-mise-sync-tools.{ps1,sh}.tmpl` が `corepack enable` することで供給していた。

Node.js 25 で Corepack の同梱が廃止された（nodejs/node [PR #57617](https://github.com/nodejs/node/pull/57617) `build: stop distributing Corepack`、[PR #59835](https://github.com/nodejs/node/pull/59835) `build: remove corepack from release tarballs`。いずれも `CHANGELOG_V25.md` に記載）。`node = "lts"` が Node 26 LTS へ上がった時点で corepack は恒久的に失われ、pnpm の供給が黙って途絶える。

発端は Windows での `chezmoi update` が `Unable to find type [Microsoft.PowerShell.PSConsoleReadLine]` を 2 回出力した事象で、経路は実機で次のとおり確認した。

1. chezmoi は `.ps1` を既定の interpreter `pwsh -NoLogo -File` で実行する（`chezmoi dump-config` で確認）。`-NoProfile` が付かないためプロファイルが読まれる。
2. プロファイルの `mise activate pwsh` が登録する CommandNotFound ハンドラは `[Microsoft.PowerShell.PSConsoleReadLine]::GetHistoryItems()` を参照する。非対話 pwsh では PSReadLine が読み込まれず型解決に失敗する。
3. `run_onchange_after_15-mise-sync-tools.ps1` の `Get-Command -Name 'corepack'` が失敗してハンドラが発火した。

corepack が消えた直接原因は、node の再インストールが `node.exe` のロックで中断し削除だけが進んだこと（install dir から欠落していたのは zip 内アルファベット順で `node.exe` 直前までの `CHANGELOG.md` / `corepack` / `corepack.cmd` / `install_tools.bat` / `LICENSE` の 5 ファイル）である。これは環境の破損であり本 ADR の対象ではないが、corepack が消えると pnpm が黙って供給されなくなる構造が露呈した。

## Decision

corepack への依存をやめ、pnpm を mise で直接管理する。

- `home/dot_config/mise/config.toml.tmpl` に `pnpm = "latest"` を追加する（backend は既定の `aqua:pnpm/pnpm`）。
- `home/run_onchange_after_15-mise-sync-tools.{ps1,sh}.tmpl` から corepack 有効化ブロックを削除する。
- `home/run_onchange_after_21-link-mise-shims.sh.tmpl` の `EXCLUDE_EXACT` の `corepack` を `pnpm` へ置き換える。npm / npx を除外しているのと同じ理由で、`~/.local/bin` 経由に予期せぬバージョンが拾われる副作用を避ける（ADR-003）。
- `home/dot_config/mise/private_mise.lock` に pnpm 11.17.0 のエントリを 5 プラットフォーム分追加する（ADR-021）。

corepack 前提を維持して今回のエラー箇所だけを塞ぐ案は、Node 26 LTS への更新時に同じ問題が再発するため採らない。yarn も mise 管理に加える案は、リポジトリに yarn の利用実績がなく lockfile と install の対象を増やす費用に見合わないため見送る。必要になった時点で `aqua:yarnpkg/berry` 等を追加する。

## Consequences

- pnpm のバージョンが lockfile で固定され、`mise install` の provenance 検証（github-attestations）の対象になる。
- corepack が消えても pnpm の供給は影響を受けない。
- yarn / pnpx / yarnpkg は提供されなくなる。

## 引き継ぐ検証

非対話 pwsh で mise の CommandNotFound ハンドラがエラーを出す構造そのものは残っている。今回消えたのは発火点だけで、chezmoi の ps1 スクリプトで別のコマンドが見つからなければ再発する。
