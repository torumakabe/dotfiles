# Copilot Instructions（リポジトリレベル）

このリポジトリは **chezmoi** と **mise** でクロスプラットフォームの dotfiles を管理している。

このファイルと `.github/agents/` はリポジトリ自身用、`home/` 配下は開発環境への配布用である。管理境界は `docs/copilot-cli.md` を参照する。

## 知識ソース

- **設計判断**: `docs/adr/INDEX.md`（形式と一覧）
- **運用ノート**: `docs/architecture.md` / `docs/operations.md` / `docs/troubleshooting.md` / `docs/copilot-cli.md`
- **エージェント**: `.github/agents/` の `manage-adr`（ADR ライフサイクル）、`review-repo`（リポジトリ整頓）

## 記述の置き場所

指示や文書の変更時は、配布用指示のソースにある[記述の置き場所](../home/private_dot_copilot/copilot-instructions.md#記述の置き場所)を参照する。このリポジトリでの割り当ては次のとおり。

- 判断の記録は `docs/adr/`
- 手順と構造の文書は `docs/`
- 回避策の撤去条件と対象範囲は「ワークアラウンド（定期チェック対象）」へ集約する

## Copilot Guard 変更時の注意

- パス比較前に `\` → `/` へ正規化すること。パターンファイルは `/` で記述する

## プラットフォーム機能契約

- 利用者向け機能は Windows/PowerShell、macOS/zsh、Linux/zsh、WSL/zsh で等価にする
- 公開関数、alias、補完、ツール導入を追加・変更するときは、全対象の実装と `tests/test_platform_parity.py` の共有テストを更新する。実装しない環境がある場合は、理由と適用範囲を同テストの契約と関連文書へ記録する

## chezmoi 操作のトラップ

- `private_` は属性でありターゲット名から除かれる。ソースの `private_mise.lock` はデプロイ先で `mise.lock` になる。文書ではどちらを指すかで表記を使い分ける
- `chezmoi execute-template --init` の `--stdinisatty` は既定 true で、実際の stdin を見ない。非対話経路を検査するテストでは明示的に渡す。詳細は `tests/test_chezmoi_config_template.py` の `ConfigTemplateBehaviourTests` docstring

## mise 操作のトラップ

- グローバル設定の lockfile を操作する `mise lock` では **`--global`** と **`--platform`** を必ず指定する。理由と対象プラットフォームは [`docs/operations.md`](../docs/operations.md#手動操作の重要ルール) を参照する
- lockfile を書き戻すのは `mise lock` だけではない。`lockfile = true` のもとで `mise install` が実インストールを行うと、対象ツールのエントリを auto-lock が書き直す。基準集合は `[settings] lockfile_platforms`（`home/dot_config/mise/config.toml.tmpl`）が正本であり、プラットフォームを増減するときはここを変更する。ただし実行中のプラットフォームは設定に関わらず常に加わり、既存エントリは削除されない
- 同じツールとバージョンを維持したまま backend を変更すると、mise は既存の install path をインストール済みと判定し、新しい backend で再インストールしない場合がある。backend を変更した端末では、`mise install --force <tool>` または `mise uninstall <tool>@<version>` と `mise install <tool>` を一度実行する。バージョンも同時に変更し、新しい install path へ通常の `mise install` が実行される場合、この操作は不要
- backend 移行はコマンドの終了だけで完了と判断しない。`mise ls <tool>` が `missing` を表示しないこと、`mise which <tool>` が新 backend の実体を返すこと、`<tool> --version` 等の実行確認が成功することを確認する。force install が失敗した場合は `reshim` や auto-install の無効化で回避せず、backend 固有の install path と検証コマンドを調査する

## プラットフォーム制約（定期チェック対象）

mise 設定を変更する際は、以下のツールの対応状況を確認し、解消されていれば条件分岐やバックエンド変更を元に戻す:

- **cargo-make**: linux/arm64 未提供（[sagiegurari/cargo-make#541](https://github.com/sagiegurari/cargo-make/issues/541)）

## ワークアラウンド（定期チェック対象）

- **Copilot sandbox の uv 専用キャッシュ**: macOS/Linux/WSL の Bash tool だけで `UV_CACHE_DIR` を切り替え、専用キャッシュを `readwritePaths` に追加する。hook なしで Python 自動探索とホストへのキャッシュ永続化が成功したら、hook、RW 許可、関連テストを撤去する。判定手順は `docs/copilot-sandbox-verification.md` を参照する
- **Copilot CLI の WindowsApps 実行エイリアス**: Windows/PowerShell だけで、WinGet 管理下の `copilot.exe` を alias に設定する。管理対象端末で WindowsApps の実行エイリアスから起動できるようになったら、alias、関連テスト、復旧手順を撤去する
- **azure-deploy の `.azure/deployment-plan.md` 参照**: このファイルだけを Copilot Guard の拒否対象から除外する。PreToolUse で呼び出し元 skill を限定できるようになるか、上流 skill が直接参照しなくなったら、許可規則と関連テストを撤去する
- **core:dotnet の Windows 導入時検証**: mise 管理の dotnet root を `DOTNET_ROOT` と PATH の先頭へ設定する。`core:dotnet` が管理下の dotnet を自動選択するようになったら、`install_env`、関連テスト、復旧手順を撤去する
- **op-ssh-sign-wsl.exe の CRLF（ADR-012）**: WSL 用 wrapper が stdout と stderr の CR を除去する。1Password が LF を出力するか、全対応 WSL で Git 2.36 以上を保証できたら wrapper と Git 設定の切替を撤去する
- **コンテナ内の git 張り替え（ADR-020）**: Codespaces と Dev Container で `/usr/local/bin/git` が 2.54 未満の場合だけ、PPA 版への symlink に置き換える。対象イメージがすべて 2.54 以上になったら `git_unshadow` を撤去する
- **npm:typescript-language-server の `trust_policy_excludes`**: npm レジストリプロキシが証跡を落とす版だけを除外する。対象版で証跡が保持されるようになったら除外を撤去し、別の版へパッケージ単位で拡張しない
- **Azure MCP Server の sandbox 化見送り**: `sandboxMcpServers: false`（ADR-026）を維持する。[#3849](https://github.com/github/copilot-cli/issues/3849)、[#3861](https://github.com/github/copilot-cli/issues/3861)、[#2112](https://github.com/github/copilot-cli/issues/2112) の解消後に Broker mode と専用 `AZURE_CONFIG_DIR` を再検討する
