# ADR-027: mise は OS ごとの公式成果物から導入する

## Status

Accepted

## Context

macOS で使っていた Homebrew formula の mise は、upstream が最適化した公式バイナリではなく、公式成果物との間に性能とサイズの差がある。Linux ではすでに GitHub Releases の公式アーカイブを検証して配置しており、macOS でも公式成果物を使う必要がある。一方、Windows の winget パッケージ `jdx.mise` は公式 ZIP を直接参照するため、再ビルドによる差はない。既存環境では formula 版と非 formula 版の mise が併存し得るため、移行時に既存の非 formula 版を壊さないことも要件になる。

## Decision

- macOS の `brew install mise` を廃止する。
- 現在解決される mise が Homebrew formula の実体である場合、または mise が未解決の場合に限り、mise GitHub Releases から固定版の公式アーカイブを取得し、SHA-256 検証後に導入する（既存の Linux 向け方式を macOS へ拡張）。
- formula と非 formula 版が併存し現在は非 formula 版が解決される場合、または formula が解決されるが `~/.local/bin/mise` に別の実行可能ファイルがある場合は、その既存ファイルを実行確認できたときに限り保持し、未使用の formula の削除を試みる。安全に保持できないときは異常終了し、formula は残す。
- 新規に取得した公式バイナリは、配置先と同じディレクトリで実行確認し、検証済みファイルを最終パスへ原子的に配置してから formula の削除を試みる。非 formula 版の既存 mise は置換しない。
- 公式バイナリの配置または既存の非 formula 版の実行確認によって mise の利用可能性を確保した後は、formula の削除失敗を移行全体の失敗としない。警告し、formula が残る場合は手動削除を求め、cleanup の失敗だけで `chezmoi apply` を継続的に失敗させない。
- Windows は winget/DSC による導入を維持する。
- 全 OS の mise 版を同期する仕組みや共通インストーラーは追加しない。公式成果物を使うことを一貫性の境界とし、OS ごとの導入機構を維持する。
- `mise.run` は使わず、明示的な固定版と SHA-256 検証を維持する。

## Consequences

Unix 系では upstream の最適化済みバイナリを利用でき、取得物の完全性と版を明示的に検証できる。検証済みバイナリを原子的に配置してから formula の削除を試みるため、移行途中の失敗で mise を壊すことはない。formula 以外から導入された既存の mise は、自動移行のために置換されない。mise の利用可能性を確保した後に formula の削除へ失敗しても自動適用は妨げられないが、formula が残る場合は利用者による手動削除が必要になる。Windows を含む全 OS で公式成果物を使う一方、導入経路と版の更新時期は OS 間で異なり得る。

Homebrew formula の移行分岐は永続的な通常処理ではなく、既存端末を移行するための暫定処理である。撤去条件と対象範囲は `.github/copilot-instructions.md` の「ワークアラウンド（定期チェック対象）」を参照し、本 ADR には重複して記載しない。
