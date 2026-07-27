# ADR-021: lockfile の対象プラットフォームは lockfile_platforms で固定する

## Status

Accepted

## Context

Codespace で `chezmoi status` が `MM .config/mise/mise.lock` を示し、`chezmoi apply` が「has changed since chezmoi last wrote it?」と問い合わせて TTY の無い環境で停止した。差分の方向を確認すると、source（`home/dot_config/mise/private_mise.lock`）は git クリーンで、デプロイ済みの `~/.config/mise/mise.lock` に 129 行のプラットフォームエントリ（`linux-arm64-musl`、`linux-x64-baseline`、`linux-x64-musl`、`linux-x64-musl-baseline`、`windows-x64-baseline`）が追加されていた。バージョンと既存 URL は変わらず、source は deployed の厳密な部分集合だった。

原因は `[settings] lockfile = true` のもとでの auto-lock である。`mise install` が実インストールを行うと、mise は対象ツールのエントリを musl と baseline を含む既定のプラットフォーム集合で書き直す（mise [PR #8277](https://github.com/jdx/mise/pull/8277)）。リポジトリは同種の混入を `mise lock --global --platform ...` という CLI フラグで防いでいたが、`mise install` 経由の書き戻しはこのフラグでは塞げない。

## Decision

`home/dot_config/mise/config.toml.tmpl` の `[settings]` に mise 標準設定 `lockfile_platforms` を追加し、auto-lock と `--platform` を省略した `mise lock` が使う基準集合を固定する。

```toml
lockfile_platforms = ["linux-x64", "linux-arm64", "macos-arm64", "windows-x64", "windows-arm64"]
```

この設定は mise [PR #8966](https://github.com/jdx/mise/pull/8966) で追加された公式機能であり、`2026.4.8` 以降に含まれる。環境変数を各スクリプトへ配る独自の仕組みを作るより、mise の標準設定に委ねる方を選んだ。

集合は mise の既定（`linux-arm64`、`linux-arm64-musl`、`linux-x64`、`linux-x64-musl`、`macos-arm64`、`macos-x64`、`windows-x64` の 7 種）とは一致させない。musl 系はこの dotfiles の対象外であり、`macos-x64` は macOS を Apple Silicon に限定するため除く。代わりに既定に無い `windows-arm64` を加える。

`mise-upgrade`（zsh の関数と PowerShell の `Invoke-MiseUpgrade`）が持つ明示的な `mise lock --global --platform ...` は残す。この処理は既存 lockfile を削除してから再生成する破壊的操作であり、設定が読まれない状況（`2026.4.8` 未満の mise、設定ファイルの欠落）でも意図した集合になることを保証する必要があるため。プラットフォーム集合の正本は config.toml とし、`tests/test_mise_config.py` が config.toml を TOML として解析した値から CLI の CSV を導出して、zsh / PowerShell / 文書との一致を検査する。

## Consequences

以下は mise 2026.7.12 linux-x64 で実測した結果である。

- **発火条件は実インストール。** `mise install` が実際にツールを導入したときだけ lockfile を書き戻す。`all tools are installed` で終わる場合は変更しない。クリーンな lockfile から `mise uninstall yq && mise install yq` を実行すると、設定が無い場合は musl / baseline 5 種が付き、設定がある場合はドリフトしなかった。
- **現在のプラットフォームは設定値に関わらず加わる。** 設定を `macos-arm64,windows-x64` に絞って yq のエントリを再生成すると、実行環境の `linux-x64` を含む 3 種になった。設定は厳密な許可リストではなく、集合に無い環境（musl 系など）で作業すればその分エントリが増える。
- **既存エントリは削除されない**（mise PR #9621）。不要なエントリを消すには lockfile を削除して再生成する。
- **グローバル設定なので他リポジトリの lockfile 操作にも及ぶ。** auto-lock が影響を受けるのは、そのリポジトリが `lockfile = true` を有効にしている場合に限る（`lockfile = true` 自体はグローバルからリポジトリへ波及せず、opt-in していないリポジトリでは `mise.lock` が生成されなかった）。一方 `mise lock` を明示実行した場合は、`lockfile = true` の有無に関わらずこの基準集合が使われる。別の集合が必要なときは `--platform` の明示で上書きできる（明示値が設定より優先されることを確認済み）。
- **`2026.4.8` 未満の mise では設定が警告なく無視される。** `run_once_before_20-install-mise.sh` は既存の mise があるとバージョンを問わず何もしないため、古い mise を持つ既存端末では従来どおりドリフトする。ただしドリフトは `chezmoi apply` が検知するため、沈黙したまま進むことはない。復旧手順は `docs/troubleshooting.md` に記す。
- **musl / baseline の全面禁止は検査できない。** bun は musl / baseline をリリース成果物として持つため、source lockfile にも正当なエントリが数件ある。

## 関連

- ADR-013（mise lockfile 同期フック）は置き換えない。同 ADR の sync hook が実行する `mise install` が lockfile を書き戻し得る、という前提を補う。

## 引き継ぐ検証

- `2026.4.8` 未満の mise で設定が無視されることは、公式のリリース内容から判断した。古い mise を用意しての実測は行っていない。
