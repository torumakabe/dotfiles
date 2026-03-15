# Copilot Instructions（リポジトリレベル）

このリポジトリは **chezmoi** と **mise** でクロスプラットフォームの dotfiles を管理している。

## Copilot Guard 変更時の注意

- パス比較前に `\` → `/` へ正規化すること。パターンファイルは `/` で記述する

## mise 操作のトラップ

- `mise lock` は**常に `--platform` を指定する**。引数なしだと既定の 8 プラットフォーム（musl 含む）が対象になり、意図しないエントリが増える
- `GITHUB_TOKEN` を `.zshrc` 等の環境変数に常駐させないこと（エージェントへの機密情報露出を防ぐため）

## プラットフォーム制約（定期チェック対象）

mise 設定を変更する際は、以下のツールの対応状況を確認し、解消されていれば条件分岐やバックエンド変更を元に戻す:

- **cargo-make**: linux/arm64 未提供（[sagiegurari/cargo-make#541](https://github.com/sagiegurari/cargo-make/issues/541)）
- **edit**: macOS 未提供（[releases](https://github.com/microsoft/edit/releases) を確認）
- **azure-dev**: macOS では mise `github:` バックエンドがバイナリ名を正規化しない（`azd-darwin-arm64` → `azd`）ため brew で管理。非 macOS は `github:` バックエンド使用（aqua レジストリが linux/arm64 未対応: [aqua registry](https://github.com/aquaproj/aqua-registry/blob/main/pkgs/Azure/azure-dev/registry.yaml) を確認）
- **dev-proxy**: macOS では mise `github:` バックエンドが誤アセット（`DevProxy.Abstractions`）を取得するため brew で管理（[dotnet/dev-proxy releases](https://github.com/dotnet/dev-proxy/releases) で macOS arm64 対応を確認）

## ワークアラウンド（定期チェック対象）

- **Azure CLI SyntaxWarning**: `dot_zshrc.tmpl` の `az()` ラッパー。[Azure/azure-sdk-for-python#38618](https://github.com/Azure/azure-sdk-for-python/issues/38618) が Close されたら削除する
