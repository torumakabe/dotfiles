# ADR-004: azd と copilot-cli を mise 外で管理する

## Status

Accepted

## Context

`azd`（Azure Developer CLI）と `copilot-cli`（GitHub Copilot CLI）は、mise の `github:` バックエンドで管理しようとすると次の問題がある:

- `azd`: mise `github:` がバイナリ名を正規化しないため、展開後に `azd` として呼び出せない
- `copilot-cli`: mise の更新タイミング遅延があり、さらに CLI 自身の `copilot update` 後は mise が旧バージョンを認識してしまう

いずれも公式配布チャネルは完備されている。

## Decision

両ツールを mise 設定から除外し、OS ごとの公式手段で管理する:

| ツール | macOS | Windows | Linux | 更新 |
| --- | --- | --- | --- | --- |
| azd | brew | winget | `install-azd.sh` | `azd update` |
| copilot-cli | brew | winget | `gh.io/copilot-install` | `copilot update` |

`home/run_once_before_10-install-packages.sh.tmpl` で初期導入する。

## Consequences

- 公式更新経路と mise のズレに悩まされない
- ただし mise 中心の世界観から外れるツールが 2 つ存在することを運用者が意識する必要がある
- `copilot-cli` は `~/.copilot/config.json` の `staff: true` で prerelease チャネルに切替え可能
