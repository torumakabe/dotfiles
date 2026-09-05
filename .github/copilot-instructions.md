# Copilot Instructions（リポジトリレベル）

このリポジトリは **chezmoi** でクロスプラットフォームの dotfiles を管理し、ツールごとの公式導入経路を使用している。

## 知識ソース

- **設計判断**: `docs/adr/` — 永続的な判断は ADR にまとめている（`docs/adr/INDEX.md`）
- **運用ノート**: `docs/architecture.md` / `docs/operations.md` / `docs/troubleshooting.md` / `docs/copilot-cli.md`
- **エージェント**: `.github/agents/` — `manage-adr`（ADR ライフサイクル）、`review-repo`（リポジトリ整頓）

## 記述の置き場所

層ごとの規範はユーザーレベルの指示に従う。このリポジトリでの割り当ては次のとおり。

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

## ワークアラウンド（定期チェック対象）

- **cargo-makeのARM64 source build**: `home/run_after_62-install-cargo-make.{sh,ps1}.tmpl` は、LinuxとWindowsのARM64向け公式release assetがないため、`home/.chezmoidata.toml` の `cargoMake.source` に固定したcrateを検証し、既存Rustup/Cargoとnative C toolchainでビルドする。対象OS/CPUで宣言版の検証可能な公式assetが提供されたら、その対象のsource build処理と専用の前提条件、関連テストを公式asset導入へ置き換える。Rustupや、他のRustビルドでも使うMSVCリンカー設定は一括撤去しない
- **Windows arm64 の公式配布物不足**: Windows arm64 では、cosign、Trivy、1Password CLI、ShellCheckの公式 amd64 実行ファイルを互換実行する。Terraform 本体は arm64 版を使うが、署名検証用の Git GPG ヘルパーには検証済みの amd64 版を使う。対象範囲は `home/.chezmoidata.toml` の `cosign.assets.windows-arm64.emulated`、`trivy.assets.windows-arm64.emulated`、`onePassword.assets.windows-arm64.emulated`、`shellcheck.winget.platforms.windows-arm64.emulated`、`terraform.verification.windowsArm64GpgEmulated` が `true` の経路に限る。GPGの例外はTerraformの署名検証だけに使用する。各対象について、宣言版（OS packageは最低版以上）の公式 Windows arm64 配布物、または検証済みの arm64 対応 Git GPG ヘルパーが利用可能になった時点で、その対象の例外と関連テストを撤去する
- **Homebrew formula 版 mise の移行案内 (ADR-027)**: `home/run_once_before_20-install-mise.sh.tmpl` は macOS で Homebrew formula 版を検出し、検証済みの公式バイナリを配置する。既存の各シェルが Homebrew の絶対パスを含む activation hook を保持するためformulaは削除せず、対象シェルをすべて終了または公式activationへ更新し、案内した実体パスを確認してから手動削除するよう案内する。管理対象の macOS 端末で移行が完了し、`brew list --formula mise` が mise を返さないことを確認できたら、Homebrew の検出、既存バイナリとの調停、移行案内と関連テストを撤去する。公式バイナリの導入処理は残す
- **azure-deploy のプロジェクト内 `.azure` 参照**: `home/private_dot_copilot/hooks/allowed-files.txt` は、`microsoft/azure-skills` の `azure-deploy` が直接読み書きする `.azure/deployment-plan.md` だけを Copilot Guard の拒否対象から除外する。ホームの `~/.azure` と、`azd` が内部管理する `.azure/<environment-name>/.env`、`.azure/config.json` は除外しない。PreToolUse がスキル識別子を提供し、呼び出し元を限定できるようになった場合、または上流スキルが `.azure/deployment-plan.md` を直接扱わなくなった場合は、この規則と関連テストを撤去する
- **op-ssh-sign-wsl.exe CRLF (ADR-012)**: `home/dot_local/bin/executable_op-ssh-sign-wrapper.sh.tmpl` で stdout/stderr の CR を剥がしている。1Password が WSL バイナリの改行を LF に揃えた場合、または全対応 WSL 経路で Git 2.36 以上を保証できるようになった場合は、wrapper と `.gitconfig-linux` の `program` 切替を撤去する
- **git の張り替え (ADR-020)**: `home/run_once_before_10-install-packages.sh.tmpl` の `git_unshadow` が、Codespaces と Dev Container のベースイメージが `/usr/local/bin` へソースビルドした古い git を `/usr/bin` の PPA 版へ symlink で張り替えている。ADR-020 の設定ベースフックが git 2.54 以上を要求するためである。対象イメージの `/usr/local/bin/git` がすべて 2.54 以上になったら、関数と呼び出しを撤去する（`devcontainers/base:ubuntu` は 2.55.0 で条件を満たす。Codespaces universal 5.1.5 は 2.53.0 で満たさない）
- **Azure MCP Server の sandbox 化見送り**: `sandboxMcpServers: false`（ADR-026）を維持し、Broker mode（`AZURE_MCP_ONLY_USE_BROKER_CREDENTIAL=true`）や専用 `AZURE_CONFIG_DIR` は導入していない。実装物は無く、上流の sandbox 基盤自体が未成熟なため保留している。[github/copilot-cli#3849](https://github.com/github/copilot-cli/issues/3849)（Windows sandbox 起動不可）、[#3861](https://github.com/github/copilot-cli/issues/3861)（cross-platform 分離の文書相違）、[#2112](https://github.com/github/copilot-cli/issues/2112)（MCP OAuth token の keychain 残留）のいずれかが解消したら再検討する
