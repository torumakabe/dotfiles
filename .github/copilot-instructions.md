# Copilot Instructions（リポジトリレベル）

このリポジトリは **chezmoi** と **mise** でクロスプラットフォームの dotfiles を管理している。

## 知識ソース

- **設計判断**: `docs/adr/` — 永続的な判断は ADR にまとめている（`docs/adr/INDEX.md`）
- **運用ノート**: `docs/architecture.md` / `docs/operations.md` / `docs/troubleshooting.md` / `docs/copilot-cli.md`
- **エージェント**: `.github/agents/` — `manage-adr`（ADR ライフサイクル）、`review-repo`（リポジトリ整頓）

## Copilot Guard 変更時の注意

- パス比較前に `\` → `/` へ正規化すること。パターンファイルは `/` で記述する

## プラットフォーム機能契約

- 利用者向け機能は Windows/PowerShell、macOS/zsh、Linux/zsh、WSL/zsh で等価にする
- 公開関数、alias、補完、ツール導入を追加・変更するときは、全対象の実装と `tests/test_platform_parity.py` の共有テストを更新する。実装しない環境がある場合は、理由と適用範囲を同テストの契約と関連文書へ記録する

## mise 操作のトラップ

- `mise lock` はデフォルトでプロジェクトレベルの設定のみ対象にするため、グローバル設定には **`--global`** が必須。また `--platform` を省略すると mise の既定集合（musl を含む 7 種）が対象になるため、**`--platform` も常に指定する**
- lockfile を書き戻すのは `mise lock` だけではない。`lockfile = true` のもとで `mise install` が実インストールを行うと、対象ツールのエントリを auto-lock が書き直す。基準集合は `[settings] lockfile_platforms`（`home/dot_config/mise/config.toml.tmpl`）が正本であり、プラットフォームを増減するときはここを変更する。ただし実行中のプラットフォームは設定に関わらず常に加わり、既存エントリは削除されない
- 同じツールとバージョンを維持したまま backend を変更すると、mise は既存の install path をインストール済みと判定し、新しい backend で再インストールしない場合がある。backend を変更した端末では、`mise install --force <tool>` または `mise uninstall <tool>@<version>` と `mise install <tool>` を一度実行する。バージョンも同時に変更し、新しい install path へ通常の `mise install` が実行される場合、この操作は不要
- backend 移行はコマンドの終了だけで完了と判断しない。`mise ls <tool>` が `missing` を表示しないこと、`mise which <tool>` が新 backend の実体を返すこと、`<tool> --version` 等の実行確認が成功することを確認する。force install が失敗した場合は `reshim` や auto-install の無効化で回避せず、backend 固有の install path と検証コマンドを調査する

## プラットフォーム制約（定期チェック対象）

mise 設定を変更する際は、以下のツールの対応状況を確認し、解消されていれば条件分岐やバックエンド変更を元に戻す:

- **cargo-make**: linux/arm64 未提供（[sagiegurari/cargo-make#541](https://github.com/sagiegurari/cargo-make/issues/541)）

## ワークアラウンド（定期チェック対象）

- **op-ssh-sign-wsl.exe CRLF (ADR-012)**: `home/dot_local/bin/executable_op-ssh-sign-wrapper.sh.tmpl` で stdout/stderr の CR を剥がして `git verify-commit` を成立させている。1Password が WSL バイナリの改行を LF に揃えた、または git 本体が find-principals 結果の `\r` を剥がすようになったら wrapper と `.gitconfig-linux` の `program` 切替を撤去する
- **git の張り替え (ADR-020)**: `home/run_once_before_10-install-packages.sh.tmpl` の `git_unshadow` が、Codespaces と Dev Container のベースイメージが `/usr/local/bin` へソースビルドした古い git を `/usr/bin` の PPA 版へ symlink で張り替えている。ADR-020 の設定ベースフックが git 2.54 以上を要求するためである。対象イメージの `/usr/local/bin/git` がすべて 2.54 以上になったら、関数と呼び出しを撤去する（`devcontainers/base:ubuntu` は 2.55.0 で条件を満たす。Codespaces universal 5.1.5 は 2.53.0 で満たさない）
