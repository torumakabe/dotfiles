# ADR-027: mise は OS ごとの公式成果物から導入する

## Status

Superseded by ADR-028

## Context

macOS で使っていた Homebrew formula 版 mise は、upstream の公式成果物との間に性能とサイズの差があった。Linux と同じ公式アーカイブへ移行する必要があったが、formula 版の activation hook は Homebrew 配下の絶対パスを親シェルに保持する。bootstrap 中に formula を削除すると、処理後の親シェルが存在しない実行ファイルを呼び出す。

## Decision

- macOS で formula 版 mise が解決される場合は、固定版の公式アーカイブを SHA-256 検証し、`~/.local/bin/mise` へ原子的に配置する。
- 既存の非 formula 版 mise は置換しない。
- bootstrap 中は formula を削除せず、公式バイナリの確認後に利用者が既存シェルを終了して手動削除する。
- Windows は winget/DSC、Linux は公式アーカイブによる導入を維持する。

## Consequences

公式成果物を配置しても、formula を削除するまでは両方の mise が併存する。移行完了には、新しいログインシェルで解決先を確認し、formula 版の activation を読み込んだ全シェルを終了する必要がある。この一時的な自動移行判断は、bootstrap を未導入環境への初期配置に限定する ADR-028 で置き換えた。
