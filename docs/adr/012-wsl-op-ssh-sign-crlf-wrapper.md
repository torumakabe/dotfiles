# ADR-012: WSL では op-ssh-sign-wsl.exe を CR 除去ラッパー経由で呼ぶ

## Status

Accepted

## Context

WSL 上で 1Password の SSH 署名 (`gpg.format = ssh`) を使うと、`git verify-commit` / `git log --show-signature` が `Could not verify signature.` で失敗する。原因は git と 1Password の Windows バイナリの間の改行の不整合:

1. git は `op-ssh-sign-wsl.exe -Y find-principals` を呼び stdout から principal を取り出す
2. Windows 流に CRLF で出力されるため `993850+...github.com\r\n` となる
3. git は `\n` のみを剥がし、`-I '993850+...github.com\r'` を後段の `-Y verify` に渡す
4. allowed_signers の principal は `\r` を含まないので照合が失敗する

`strace` で `\r` 混入を確認済み、ローカル `ssh-keygen -Y verify` ではファイルもキーも有効、commit object 自体は正常に署名されている（GitHub 側の Verified 表示には影響しない）。WSL+op-ssh-sign-wsl.exe 固有の interop 問題で、Linux ネイティブ (`/opt/1Password/op-ssh-sign`) や Windows ネイティブ (`op-ssh-sign.exe`) では発生しない。

## Decision

WSL 限定で `op-ssh-sign-wsl.exe` の stdout/stderr から CR を剥がすラッパー `~/.local/bin/op-ssh-sign-wrapper.sh` を経由させる。`isWSL` データで 3 ヶ所をゲート:

| 配置 | WSL | ネイティブ Linux | macOS / Windows |
| --- | --- | --- | --- |
| `~/.local/bin/op-ssh-sign-wrapper.sh` | 配置 | `home/.chezmoiignore` で除外 | `.gitconfig-linux` ごと除外 |
| `gpg.ssh.program` | wrapper を指す | `/opt/1Password/op-ssh-sign` | 各 OS の値 |

署名 (`-Y sign`) は `-s <file>` にバイナリを書き出し stdout を経由しないため、CR 除去で改ざんされない。

## Consequences

- WSL でも `git verify-commit` / `git log --show-signature` がローカル検証できる
- 1Password が CRLF 出力を改善した場合は wrapper を撤去できる（`.github/copilot-instructions.md` のワークアラウンド節で追跡）
- 将来 git 本体が find-principals 出力の `\r` を剥がすよう修正された場合も同様に撤去可能
- wrapper は bash の `set -o pipefail` と process substitution に依存するため、`/usr/bin/env bash` が必須
