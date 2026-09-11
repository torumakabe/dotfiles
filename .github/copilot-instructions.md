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

- **Copilot CLI の WindowsApps 実行エイリアス**: Windows/PowerShell の `home/PowerShell_profile.ps1.tmpl` は、ユーザー単位の WinGet 管理下に `copilot.exe` がある場合に限り、`copilot` alias をその実体へのリンクへ設定する。`WindowsApps\copilot.exe` が「プロセスにパッケージ ID がありません」で起動できない問題を回避するためである。PATH、アプリの登録、sandbox 設定は変更しない。WinGet 管理下に実体がなければ既存の解決方法を維持し、macOS/Linux/WSL は対象外とする。管理対象の Windows 端末すべてで WindowsApps の実行エイリアスから CLI が起動できるようになったら、この alias 設定と関連テスト、`docs/troubleshooting.md` の復旧手順を撤去する
- **Homebrew formula 版 mise の移行案内 (ADR-027)**: `home/run_once_before_20-install-mise.sh.tmpl` は macOS で Homebrew formula 版を検出し、検証済みの公式バイナリを配置する。既存の各シェルが Homebrew の絶対パスを含む activation hook を保持するため formula は削除せず、対象シェルをすべて終了または公式 activation へ更新し、案内した実体パスを確認してから手動削除するよう案内する。管理対象の macOS 端末で移行が完了し、`brew list --formula mise` が mise を返さないことを確認できたら、Homebrew の検出、既存バイナリとの調停、移行案内と関連テストを撤去する。公式バイナリの導入処理は残す
- **azure-deploy のプロジェクト内 `.azure` 参照**: `home/private_dot_copilot/hooks/allowed-files.txt` は、`microsoft/azure-skills` の `azure-deploy` が直接読み書きする `.azure/deployment-plan.md` だけを Copilot Guard の拒否対象から除外する。ホームの `~/.azure` と、`azd` が内部管理する `.azure/<environment-name>/.env`、`.azure/config.json` は除外しない。PreToolUse がスキル識別子を提供し、呼び出し元を限定できるようになった場合、または上流スキルが `.azure/deployment-plan.md` を直接扱わなくなった場合は、この規則と関連テストを撤去する
- **core:dotnet Windows install-time verification**: `home/dot_config/mise/config.toml.tmpl` は Windows の `dotnet.install_env` で `%LOCALAPPDATA%\mise\dotnet-root` を `DOTNET_ROOT` と PATH の先頭へ設定する。mise の `core:dotnet` が install-time verification へ管理下の dotnet を自動設定するようになったら、このオプションと関連テスト、`docs/troubleshooting.md` の復旧手順を撤去する
- **op-ssh-sign-wsl.exe CRLF (ADR-012)**: `home/dot_local/bin/executable_op-ssh-sign-wrapper.sh.tmpl` で stdout/stderr の CR を剥がしている。1Password が WSL バイナリの改行を LF に揃えた場合、または全対応 WSL 経路で Git 2.36 以上を保証できるようになった場合は、wrapper と `.gitconfig-linux` の `program` 切替を撤去する
- **git の張り替え (ADR-020)**: `home/run_once_before_10-install-packages.sh.tmpl` の `git_unshadow` が、Codespaces と Dev Container のベースイメージが `/usr/local/bin` へソースビルドした古い git を `/usr/bin` の PPA 版へ symlink で張り替えている。ADR-020 の設定ベースフックが git 2.54 以上を要求するためである。対象イメージの `/usr/local/bin/git` がすべて 2.54 以上になったら、関数と呼び出しを撤去する（`devcontainers/base:ubuntu` は 2.55.0 で条件を満たす。Codespaces universal 5.1.5 は 2.53.0 で満たさない）
- **npm:typescript-language-server の trust_policy_excludes**: 利用中の npm レジストリプロキシが `home/dot_config/mise/config.toml.tmpl` に記載した版の `_npmUser.trustedPublisher` を落とし、証跡を持つ版からの後退と判定されるため除外している。対象版は同設定の version literal を正本とする。プロキシが証跡を保持するようになったら除外を撤去する。別の版で同じ失敗が出たら、パッケージ名だけの除外へ広げず、その版を明記して追加する
- **Copilot sandbox の専用 uv cache (ADR-030)**: Copilot runtime が通常の uv cache を read-only で許可するため、`home/run_onchange_after_35-configure-copilot-sandbox.sh.tmpl` と `.ps1.tmpl` は Copilot 専用 cache を `readwritePaths` へ追加し、`home/private_dot_copilot/hooks/scripts/executable_uv-enforcer.py` は全 bash/PowerShell tool call の command 内へ `UV_CACHE_DIR` を設定する。PowerShell では元の command を同じ PowerShell 実体の子プロセスへ `EncodedCommand` として渡し、構文と終了コードを維持する。`hooks.json` は Node.js と Copilot Guard が原文を検査した後に uv-enforcer が command を変更する順序を維持する。sandbox の有効状態や command が uv を直接含むかにかかわらず hook が適用される。CLI や MXC の版、issue の状態だけでは撤去せず、`docs/copilot-sandbox-verification.md` の撤去判定プローブが sandbox 有効時の Windows、macOS、native Linux、WSL2 で個別に成功したら、専用 cache の grant と command 変更、hook 順序への依存、関連テストと文書を一括して撤去する。撤去時は sandbox policy version を更新し、リポジトリが管理する `github-copilot/uv` と `GitHubCopilot\uv` の完全一致 entry を各端末の `readwritePaths` から削除する移行処理を入れる。専用 cache directory の削除は利用者へ案内し、自動削除しない。現時点では WSL2 と macOS の回避策適用後を検証済みで、macOS の撤去判定プローブも成功している。Windows ProcessContainer では専用 cache を使う実行に成功したが、終了コードの維持を修正した版の再検証が必要である。WSL2 の撤去判定と native Linux の実動作は未確認である
- **Azure MCP Server の sandbox 化見送り**: `sandboxMcpServers: false`（ADR-026）を維持し、Broker mode（`AZURE_MCP_ONLY_USE_BROKER_CREDENTIAL=true`）や専用 `AZURE_CONFIG_DIR` は導入していない。実装物は無く、上流の sandbox 基盤自体が未成熟なため保留している。[github/copilot-cli#3849](https://github.com/github/copilot-cli/issues/3849)（Windows sandbox 起動不可）、[#3861](https://github.com/github/copilot-cli/issues/3861)（cross-platform 分離の文書相違）、[#2112](https://github.com/github/copilot-cli/issues/2112)（MCP OAuth token の keychain 残留）のいずれかが解消したら再検討する
