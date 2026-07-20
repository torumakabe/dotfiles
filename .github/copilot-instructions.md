# Copilot Instructions（リポジトリレベル）

このリポジトリは **chezmoi** と **mise** でクロスプラットフォームの dotfiles を管理している。

## 知識ソース

- **設計判断**: `docs/adr/` — 永続的な判断は ADR にまとめている（`docs/adr/INDEX.md`）
- **運用ノート**: `docs/architecture.md` / `docs/operations.md` / `docs/troubleshooting.md` / `docs/copilot-cli.md`
- **エージェント**: `.github/agents/` — `manage-adr`（ADR ライフサイクル）、`review-repo`（リポジトリ整頓）

## Copilot Guard 変更時の注意

- パス比較前に `\` → `/` へ正規化すること。パターンファイルは `/` で記述する

## mise 操作のトラップ

- `mise lock` はデフォルトでプロジェクトレベルの設定のみ対象にするため、グローバル設定には **`--global`** が必須。また引数なしだと既定の 8 プラットフォーム（musl 含む）を対象にするため、**`--platform` も常に指定する**

## プラットフォーム制約（定期チェック対象）

mise 設定を変更する際は、以下のツールの対応状況を確認し、解消されていれば条件分岐やバックエンド変更を元に戻す:

- **cargo-make**: linux/arm64 未提供（[sagiegurari/cargo-make#541](https://github.com/sagiegurari/cargo-make/issues/541)）

## ワークアラウンド（定期チェック対象）

- **Azure CLI SyntaxWarning**: `dot_zshrc.tmpl` の `az()` ラッパー。[Azure/azure-sdk-for-python#38618](https://github.com/Azure/azure-sdk-for-python/issues/38618) が Close されたら削除する
- **op-ssh-sign-wsl.exe CRLF (ADR-012)**: `home/dot_local/bin/executable_op-ssh-sign-wrapper.sh.tmpl` で stdout/stderr の CR を剥がして `git verify-commit` を成立させている。1Password が WSL バイナリの改行を LF に揃えた、または git 本体が find-principals 結果の `\r` を剥がすようになったら wrapper と `.gitconfig-linux` の `program` 切替を撤去する
