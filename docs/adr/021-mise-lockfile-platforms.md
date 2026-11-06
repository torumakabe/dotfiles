# ADR-021: lockfile の対象プラットフォームは lockfile_platforms で固定する

## Status

Accepted

## Context

`lockfile = true` のもとでは、`mise install` が実インストール後に lockfile を書き戻す。対象環境を指定しないと、配布対象外のプラットフォームが追加され、非対話の `chezmoi apply` が差分確認で停止する。手動の `mise lock --platform ...` だけでは、この auto-lock を制御できない。

## Decision

`home/dot_config/mise/config.toml.tmpl` の `lockfile_platforms` を対象環境の定義元とする。環境変数を独自に配布せず、mise 2026.4.8 以降の[標準設定](https://github.com/jdx/mise/pull/8966)を使う。

musl 系は対象外、macOS は Apple Silicon 限定（ADR-034）とし、Windows ARM64 も対象に含める。具体的な集合と操作方法は [`operations.md`](../operations.md#対象プラットフォームの定義元) に記載する。

`mise-upgrade` の明示的な `--global --platform ...` は維持する。lockfile を削除して再生成する際、設定が欠落していても意図した集合を指定するためである。両シェルと文書の集合は、config から導出した値で一致を検査する。

## Consequences

- auto-lock と明示的な再生成で対象環境をそろえられる。ADR-013 の同期処理は維持する。
- 実行中のプラットフォームは設定外でも加わり、既存エントリも削除されない。厳密な許可リストにはならない。
- グローバル設定は他リポジトリにも適用される。auto-lock は各リポジトリの `lockfile = true`、明示的な `mise lock` はその設定の有無によらず影響を受ける。
- 古い mise は設定を利用できないため更新が必要になる。復旧は [`troubleshooting.md`](../troubleshooting.md#miselock-has-changed-since-chezmoi-last-wrote-it-と聞かれる) を参照する。
