# ADR-034: macOS のサポートは Apple Silicon (arm64) 限定とする

## Status

Accepted

## Context

README.md の対応環境表は以前から「macOS は Apple Silicon のみ」と記載しており、ADR-021 も `macos-x64` を lockfile の対象から外す理由としてこの前提を挙げていた。しかし前提そのものを記録した ADR が無く、実装には Intel Mac (x86_64) 向けの分岐が残っていた。新しく追加した Copilot CLI の導入スクリプトを arm64 のみ対応にした際、この不整合が表面化した。

Intel 向け分岐を維持すると、macOS 用の成果物と SHA-256 pin、Homebrew prefix を常に 2 系統ぶん調べ続けることになる。実機での検証は行っておらず、動作を保証できない分岐を抱えた状態だった。

## Decision

macOS のサポート対象を Apple Silicon (arm64) 限定とし、Intel Mac 向けの分岐を実装に持たない。具体的には chezmoi bootstrap の `darwin-amd64` 取得、rustup の `x86_64-apple-darwin` 系分岐、Homebrew 検出における Intel prefix (`/usr/local`) フォールバックを置かない。

Intel Mac では install.sh が `unsupported platform: darwin-amd64` で停止する。暗黙に中途半端な導入が進むことを避け、非対応であることを早い段階で示す。

例外として、pnpm 等が全プラットフォーム向けの任意依存を記録した生成物（mise lockfile の sidecar など）に含まれる `x64` エントリは手動編集しない。内容はツールの解決結果であり、手で書き換えても次の生成で失われるため。

## Consequences

- macOS 向けに維持する成果物・SHA-256 pin・Homebrew prefix が 1 つに減り、ツールを追加するたびに Intel 用の成果物と checksum を調べる必要が無くなる。
- Intel Mac は対象外となる。利用するには削除した分岐の再追加と、その実機での検証が必要になる。
- README.md の記載と実装が一致し、ADR-021 が前提にしていた判断の根拠がこの ADR に定まる。
