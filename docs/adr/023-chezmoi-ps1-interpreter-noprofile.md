# ADR-023: chezmoi の ps1 実行系を固定しプロファイルを読ませない

## Status

Accepted

## Context

chezmoi の既定の `.ps1` 実行はユーザープロファイルを読み込む。mise の CommandNotFound ハンドラが登録されると、非対話 PowerShell にない PSReadLine の型を参照し、コマンドの存在確認でエラーになる。

スクリプトはプロファイルに依存しない。alias、関数、PATH 改変を持ち込まない実行環境に固定する必要がある。

## Decision

`home/.chezmoi.toml.tmpl` の `[interpreters.ps1]` を `pwsh -NoLogo -NoProfile -File` に固定する。プロファイル由来の副作用を排除し、スクリプトは Machine+User の PATH を使う。

## Consequences

- chezmoi のスクリプトは、プロファイルの関数や PATH 追加に依存できなくなる。Windows の mise 管理ツールの実行パスは ADR-013 と ADR-037 で扱う。
- 設定変更であるため、反映には `chezmoi init` の再実行が必要になる。
- chezmoi 以外がプロファイルを読み込んで起動する PowerShell には、この設定は適用されない。
