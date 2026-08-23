# ADR-027: mise は OS ごとの公式成果物から導入する

## Status

Accepted

## Context

macOS で使っていた Homebrew formula の mise は、upstream が最適化した公式バイナリではなく、公式成果物との間に性能とサイズの差がある。Linux ではすでに GitHub Releases の公式アーカイブを検証して配置しており、macOS でも公式成果物を使う必要がある。一方、Windows の winget パッケージ `jdx.mise` は公式 ZIP を直接参照するため、再ビルドによる差はない。既存環境では formula 版と非 formula 版の mise が併存し得るため、移行時に既存の非 formula 版を壊さないことも要件になる。

Homebrew 版の `mise activate zsh` が親シェルに定義した `_mise_hook` は、`/opt/homebrew/bin/mise` の絶対パスを保持する。chezmoi の子プロセスが公式バイナリの配置直後に formula を削除しても親シェルの hook は更新できず、処理終了後に hook が存在しない実行ファイルを呼び出して失敗する。このため、公式バイナリの利用可能性を子プロセス内で確認できることは、同じ処理中に formula を安全に削除できることを意味しない。

## Decision

- macOS の `brew install mise` を廃止する。
- 現在解決される mise が Homebrew formula の実体である場合、または mise が未解決の場合に限り、mise GitHub Releases から固定版の公式アーカイブを取得し、SHA-256 検証後に導入する（既存の Linux 向け方式を macOS へ拡張）。
- 保持対象は、bootstrap 実行時に `command -v mise` で解決される非 formula 版の実体と、formula が解決される場合に標準配置先 `~/.local/bin/mise` で明示的に確認する非 formula 版の実体に限定する。いずれも対象のパスを直接実行確認できたときに限り保持し、それ以外の PATH 外にある未知の mise を探索して保持する契約は持たない。安全に保持できないときは異常終了して formula を残す。
- 新規に取得した公式バイナリの標準配置先は `~/.local/bin/mise` とする。配置先と同じディレクトリで実行確認し、検証済みファイルを最終パスへ原子的に配置する。非 formula 版の既存 mise は置換しない。
- bootstrap 中は formula を自動削除しない。公式バイナリの配置または既存の非 formula 版の実行確認後も formula を残す。移行確認では、新しい login shell における `mise` の解決先が、新規配置の場合は `~/.local/bin/mise`、既存の非 formula 版を保持する場合は保持対象として確認した実体のパスであることを確認する。bootstrap 前に `~/.local/bin` が存在しなかった場合は、継承された `__DOTFILES_PROFILE_LOADED` による PATH 再構築の省略を避けるため、ガードを解除して新しい login shell を開始する。
- formula を手動削除する前に、Homebrew 版の activation を読み込んだ既存 shell をすべて終了するか、各 shell で公式バイナリの activation を読み直す。新しい shell を一つ開始しただけでは、Homebrew の絶対パスを hook に保持する他の既存 shell は安全にならない。cleanup の失敗を警告扱いにする従来の判断は、自動 cleanup 自体を廃止するこの判断で置き換える。
- 移行確認や復旧の具体的なコマンドは ADR に置かず、operations と troubleshooting の文書で管理する。復旧時に使う実体パスは標準配置先に固定せず、bootstrap が保持対象として確認した実体、または bootstrap が新規に配置した実体のパスのいずれかとする。
- Windows は winget/DSC による導入を維持する。
- 全 OS の mise 版を同期する仕組みや共通インストーラーは追加しない。公式成果物を使うことを一貫性の境界とし、OS ごとの導入機構を維持する。
- `mise.run` は使わず、明示的な固定版と SHA-256 検証を維持する。

## Consequences

Unix 系では upstream の最適化済みバイナリを利用でき、取得物の完全性と版を明示的に検証できる。検証済みバイナリを原子的に配置するため、移行途中の失敗で mise を壊すことはない。保持対象として確認された非 formula 版の mise は、自動移行のために置換されない。保持対象は `command -v mise` が解決する実体、または formula 解決時に明示確認する `~/.local/bin/mise` に限られ、それ以外のパスにある未知の mise は bootstrap の対象外のままになる。

bootstrap 中に formula を削除しないため、親シェルに残る絶対パス参照を即座に壊さずに移行できる。一方、formula を手動削除するまでは両者が併存し、移行の完了には、保持対象または新規配置先に応じた解決先の確認と、Homebrew 版の activation を読み込んだ全既存 shell の終了または activation の再読込が必要になる。bootstrap 前に `~/.local/bin` が存在しない環境では、継承されたプロファイルガードを解除して login shell を開始しなければ、新規の標準配置先が PATH に反映されない場合がある。障害時の復旧は標準パスに固定せず、bootstrap が保持対象として確認した実体、または新規配置先の実体パスのいずれかを用いる。これらの操作と障害時の復旧手順の具体的なコマンドは operations と troubleshooting の責務になる。Windows を含む全 OS で公式成果物を使う一方、導入経路と版の更新時期は OS 間で異なり得る。

Homebrew formula の移行分岐は永続的な通常処理ではなく、既存端末を移行するための暫定処理である。撤去条件と対象範囲は `.github/copilot-instructions.md` の「ワークアラウンド（定期チェック対象）」を参照し、本 ADR には重複して記載しない。
