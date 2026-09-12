# ADR-028: mise bootstrap は既存導入を置換しない

## Status

Accepted

## Context

ADR-027 は、macOS の Homebrew formula 版 mise を公式成果物へ移行する分岐を定めた。この分岐を通常の bootstrap に残すと、導入元ごとの検出、既存シェルの activation、削除後の復旧を継続して保守する必要がある。

bootstrap の責務を未導入環境への初期配置に限定し、既存 mise の導入元変更と更新は利用者が明示的に行う。ADR-027 を本 ADR で置き換える。

## Decision

- macOS と Linux では、`command -v mise` で既存の mise を確認できる場合、導入元と版を問わず実行確認だけを行い、置換しない。
- PATH で確認できなくても `~/.local/bin/mise` が存在し、実行できる場合は保持する。
- mise が未導入の場合だけ、固定版の公式 GitHub Releases アーカイブを取得し、SHA-256 検証後に `~/.local/bin/mise` へ原子的に配置する。
- Homebrew formula の検出、自動移行、削除、削除案内は bootstrap の責務に含めない。
- Windows は winget/DSC の `jdx.mise` による導入を維持する。
- リポジトリが新規導入する mise には公式成果物を使用する。既存 mise の配布元と版はこの契約の対象外とする。

## Consequences

bootstrap は既存環境を置換せず、導入元固有の移行分岐を持たない。既存の Homebrew formula 版 mise は自動では移行されず、公式成果物への変更や既存 mise の更新は利用者が手動で実行する。

未導入の macOS と Linux では、固定版と SHA-256 を検証した公式成果物を利用できる。導入方法と更新時期は OS および既存環境によって異なり得る。
