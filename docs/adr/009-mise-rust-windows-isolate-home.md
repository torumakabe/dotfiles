# ADR-009: Windows では mise の rust home を外部 rustup から分離する

## Status

Superseded by ADR-016

## Context

Windows で mise が `rust` を install するとき、toolchain 本体を rustup 経由で配置した後に `~/.cargo/bin` を `<mise-install-dir>\rust\<version>` から symlink で参照させる。既に外部 rustup が `%USERPROFILE%\.cargo\bin` を実体ディレクトリとして保持している環境では、Windows の symlink API がディレクトリ上書きを拒否して `os error 183` で失敗する（Linux/macOS の `ln -sf` は冪等なため再現しない）。

失敗すると mise 全体が exit 1 で落ち、pre-commit hook や `uv run` など mise 経由の処理が全滅する。repo 側に cargo/rustc 依存コードは無いが、rust を mise から外すのは他 OS 利用者と対称性を崩すため避けたい。

mise 公式は `rust.cargo_home` / `rust.rustup_home`（env: `MISE_CARGO_HOME` / `MISE_RUSTUP_HOME`）で mise 専用の独立ディレクトリを指定できる（[公式 docs](https://mise.jdx.dev/lang/rust.html)）。

## Decision

Windows でのみ、`home/dot_config/mise/config.toml.tmpl` の `[settings.rust]` セクションで `cargo_home` / `rustup_home` を `%LOCALAPPDATA%\mise\rust\{cargo,rustup}` に固定する。Linux/macOS は既存挙動（外部 rustup と `~/.cargo` を共有）を維持する。

PATH 追加は行わない。Windows では `run_once_after_05-setup-mise-shims-path.ps1.tmpl` が `%LOCALAPPDATA%\mise\shims` を user PATH 先頭に積むため、`cargo` / `rustc` は shim 経由で解決できる。

## Consequences

- Windows で mise install の symlink 衝突が消え、pre-commit / `uv run` の安定化につながる
- Windows 上で「mise が管理する rust」と「外部 rustup が管理する rust」が別 toolchain になる。`cargo install` の成果物も別パスになるため、直接 `%USERPROFILE%\.cargo\bin` を叩いていた利用者は移行が必要
- Linux/macOS は変更なし。全 OS 一律の分離方針を取らないのは、shim exclude (ADR-003) のレイヤでは救えない Windows 固有問題であり、他 OS の既存 UX を壊す必要がないため

本 ADR は ADR-016 により置換された。rust を全 OS で mise 管理から除外し外部 rustup に一本化したため、本 ADR が対処していた mise/rustup home 分離は不要になった。
