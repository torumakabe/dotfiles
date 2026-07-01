# ADR-016: Rust は全 OS で外部 rustup 管理とする (mise 管理から除外)

## Status

Accepted

## Context

mise の rust shim は呼び出し時に `RUSTUP_TOOLCHAIN` 環境変数を強制注入する。rustup のトゥールチェイン優先順位は「環境変数 > rust-toolchain.toml > default」のため、mise 経由の cargo/rustc はプロジェクトの `rust-toolchain.toml` を常に無視して上書きしてしまう（実機確認: `rustup show` が `active because: overridden by environment variable RUSTUP_TOOLCHAIN` と明言）。

これは特定プロジェクト固有ではなく、`rust-toolchain.toml` を使う全プロジェクトに共通する構造的問題であり、mise で `rust = "latest"` を管理する限り解消できない。

ADR-009 は Windows 限定で「外部 rustup が既に存在する」ことを前提にした設計（mise の rust home を分離）を採用しており、この非対称性を既に部分的に前提としていた。

## Decision

全 OS (macOS/Linux/Windows) で `home/dot_config/mise/config.toml.tmpl` の `[tools]` から `rust` を除外する。rust toolchain の解決は公式 rustup + `rust-toolchain.toml` のネイティブ解決に一本化する。

導入は macOS/Linux では公式インストールスクリプト (`https://sh.rustup.rs`, `command -v rustup` が無い場合のみ) で、Windows では winget (`Rustlang.Rustup`) で行う。

## Consequences

- `rust-toolchain.toml` を持つプロジェクトのバージョン固定が正しく機能するようになる
- mise lockfile が rust バージョンを追跡しなくなる。更新は `rustup update` / `rustup default` で個別管理する
- ADR-009 が対処していた Windows 固有の mise/rustup home 分離の複雑さが不要になる（ADR-009 は本 ADR により Superseded）
- 新規マシンでは rustup のインストールタイミングが `run_once_before_10` (mise install より前) になる
