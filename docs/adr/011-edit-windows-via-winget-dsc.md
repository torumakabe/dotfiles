# ADR-011: Microsoft Edit は Windows のみ winget/DSC で管理する

## Status

Accepted

## Context

`edit`（Microsoft Edit）は当初 mise (aqua:microsoft/edit) で Windows + Linux 向けに管理していたが、次の状況がある:

- macOS 向けプリビルドバイナリは未提供で、当初から対象外
- Linux では実用上利用しておらず、mise で管理する動機が薄い
- Windows では winget に `Microsoft.Edit` が公開されており、リポジトリの GUI/コンソールアプリは既に `reference/windows/configuration.dsc.yaml` の DSC 構成に集約している

mise の役割は「クロスプラットフォームで揃えたい CLI ランタイムの版管理」に集中させ、Windows 固有のコンソール/GUI アプリは DSC に寄せる方が運用ノイズが少ない。

## Decision

`edit` を mise 設定から除外し、Windows 限定で winget/DSC によって管理する:

| OS | 管理 | 備考 |
| --- | --- | --- |
| Windows | winget/DSC (`Microsoft.Edit`) | `reference/windows/configuration.dsc.yaml` に追加 |
| Linux | 未使用 | 必要になった時点で再検討 |
| macOS | 未提供のため対象外 | 変更なし |

## Consequences

- Windows でのインストール・更新経路が他の GUI/CLI アプリ（PowerShell, Git, GitHub CLI 等）と一貫する
- mise lockfile から edit エントリが消えるため、mise の対象が CLI ランタイムに整理される
- Linux で edit を使いたくなった場合は別途インストール手段を選定する必要がある（本 ADR の更新で対応）
- `home/PowerShell_profile.ps1.tmpl` の `$env:EDITOR = 'edit'` は PATH 経由で winget 配置のバイナリを解決するため変更不要
