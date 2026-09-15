# ADR-029: mise lockfile revision 2 の npm sidecar を不可分に管理する

## Status

Accepted

## Context

mise 2026.9.7 以降の lockfile revision 2 は、npm ツールの推移依存関係を `~/.config/mise/locks/` 配下の sidecar（`aube-lock.yaml` と `package.json`）へ保存する。`mise.lock` だけを管理すると、参照先の欠落や旧版 sidecar の残存によって、記録した依存関係と配布先の状態が一致しない。

## Decision

- `mise.lock` と sidecar を不可分な生成物集合として同じ commit で管理する。
- chezmoi source は `home/dot_config/mise/private_mise.lock` と再帰的 exact directory を使う。sidecar の source 名は通常 `exact_locks` であり、権限属性が付く環境では `exact_private_locks` になるため、更新処理は `chezmoi source-path` で実体を解決する。これにより、未参照または旧版の sidecar を配布先から削除する。
- sidecar が 0 件の場合は `.keep` を配置して exact directory を Git の管理対象に残し、他端末の旧 sidecar を適用時に削除する。
- lockfile と sidecar は生成時の byte 列を保持するため、`.gitattributes` で Git の改行変換を無効にする。
- PowerShell と zsh の `mise-upgrade` は、target の lockfile と sidecar を一括退避し、両方を削除してから `mise lock --global --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64 --bump` で再生成する。`--bump` により config の selector を再解決し、npm backend の `<version>~aube~<hash>` という内部インストール名を公開版として扱わない。
- 再生成後は lockfile が参照する aube path と必須ファイルを検証してから chezmoi source を更新する。生成または source 更新に失敗した場合は、target と source を更新前の状態へ復元する。
- `run_onchange` の発火条件は `private_mise.lock` の hash のままとする。sidecar の path と digest が lockfile に含まれるため、sidecar 専用の発火条件は追加しない。
- 日常ワークフロー（OS package update、mise 本体 update、chezmoi update、mise-upgrade）は変更しない。

## Consequences

- lockfile と npm 推移依存関係を同じ履歴単位で再現でき、不要な sidecar も chezmoi apply 時に削除される。
- `mise-upgrade` は target と source の双方をトランザクションとして扱うため、途中失敗時にも更新前の生成物集合へ戻せる。
- revision 2 の sidecar 形式や参照方法が変わった場合は、両 shell の検証処理と chezmoi source 構造を同時に更新する必要がある。
