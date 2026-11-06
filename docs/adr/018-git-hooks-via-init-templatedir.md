# ADR-018: 機械全体への Git hook 配布は init.templateDir で行う

## Status

Accepted

## Context

global の `core.hooksPath` で共有ディレクトリを指定すると、lefthook 等の hook マネージャがそこへ書き込み、無関係なリポジトリにも影響する。gitleaks の配布と各プロジェクトの hook 管理を両立するため、配布後のファイルはリポジトリごとに分離する必要がある。

## Decision

global の `core.hooksPath` を廃止し、`init.templateDir = ~/.config/git/templates` で pre-commit を配布する。コピー後は通常の repo-local hook とし、別の local hook への委譲は行わない。

既存リポジトリの状態は、`ghq` 配下を読み取り専用で走査する `git-hooks-audit` で報告する。他ツールが作った hook は自動削除しない。

## Consequences

- `init.templateDir` は `git init` / `git clone` 時にコピーされ、既存ファイルを上書きしない。配布後の hook の変更は、そのリポジトリ内に限られる。
- 既存リポジトリへの配布には backfill が必要になる。操作は [`troubleshooting.md`](../troubleshooting.md#新規リポジトリに-gitleaks-pre-commit-hook-が入らない) に記載する。
- 他プロジェクトの hook マネージャが特定リポジトリの `.git/hooks/pre-commit` を上書きしても、影響はそのリポジトリ内に閉じる。
- テンプレートディレクトリは `hooks/pre-commit` のみを持ち、Git 既定の `*.sample` 等は引き継がない（この用途では無害・許容）。
- Windows: hook 本体の POSIX `sh` 互換要件（Git for Windows が `/usr/bin/env bash` を WSL の bash.exe に解決し `C:/...` パスを開けない問題への対応）は変わらず適用される。
- Git 2.54 以降では、ADR-020 の設定ベースフックが別レイヤとして加算的に走る。本 ADR の `init.templateDir` は撤去せず、Git 2.54 より前のバージョンでの唯一の配布経路として残す。
- リポジトリの作成時期に依存しない適用と無効状態の検出は ADR-020 で補う。
