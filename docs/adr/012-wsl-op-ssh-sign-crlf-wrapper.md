# ADR-012: WSL では op-ssh-sign-wsl.exe を CR 除去ラッパー経由で呼ぶ

## Status

Accepted

## Context

Git 2.36 未満の WSL では、`op-ssh-sign-wsl.exe` が返す CRLF の principal に CR が残り、`git verify-commit` / `git log --show-signature` の照合が失敗する。署名自体は正常で、GitHub 側の Verified 表示には影響しない。

Docker Desktop の WSL2 バックエンド上の Dev Container は WSL カーネルを共有するため、`isWSL` だけでは Windows バイナリを起動できるか判定できない。

## Decision

`isWSL` が真、`/proc/sys/fs/binfmt_misc/WSLInterop` が存在、`windowsUser` が空でない場合だけ、stdout/stderr から CR を除去する `~/.local/bin/op-ssh-sign-wrapper.sh` を配布し、`gpg.ssh.program` に指定する。WSL での `windowsUser` の入力も interop と TTY がある場合に限る。

`isWSL` は Docker Engine 等の導入判断にも使うため、カーネルによる判定を維持する。interop とユーザー名の条件はラッパーの配布と参照に追加し、適用時に再評価する。初期化時だけ生成するデータキーは増やさず、既存設定との互換性を保つ。

## Consequences

- WSL でも `git verify-commit` / `git log --show-signature` がローカル検証できる
- 署名はファイルへ書き出されるため、stdout/stderr の CR 除去は署名データを変更しない
- 撤去条件は [ワークアラウンド一覧](../../.github/copilot-instructions.md#ワークアラウンド定期チェック対象)で管理する
- wrapper は bash の `set -o pipefail` と process substitution に依存するため、`/usr/bin/env bash` が必須
- ラッパーの配布条件と Git の参照条件は一致させる。共有の静的検査で不一致を検出する
