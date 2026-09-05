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

- `chezmoi execute-template --init` の `--stdinisatty` は既定 true で、実際の stdin を見ない。非対話経路を検査するテストでは明示的に渡す。詳細は `tests/test_chezmoi_config_template.py` の `ConfigTemplateBehaviourTests` docstring

## ワークアラウンド（定期チェック対象）

- **旧 mise 由来の端末状態**: 現行構成は mise を導入、設定、activation、shim 生成に使用しない。一方、個別インストーラーは移行時の所有者保護として、自身の入口と同名で既知の旧 mise 実体を指す symlink だけを置換できる。この判定は実行時依存ではない。既存プロセスの activation と継承済み PATH、端末上の mise 本体、設定、shim、state、Windows の既存 User `Path` エントリは自動削除しない。macOS の旧 shim 生成処理が残した `${XDG_STATE_HOME:-$HOME/.local/state}/chezmoi-dotfiles/mise-shim-links` も移行証拠として保持する。管理対象端末の inventory と dry-run で所有関係を確認し、利用者が清掃を別途承認した後にだけ、端末側の状態と個別インストーラーの旧リンク受け入れを撤去する
- **cargo-makeのARM64 source build**: `home/run_after_62-install-cargo-make.{sh,ps1}.tmpl` は、LinuxとWindowsのARM64向け公式release assetがないため、`home/.chezmoidata.toml` の `cargoMake.source` に固定したcrateを検証し、既存Rustup/Cargoとnative C toolchainでビルドする。対象OS/CPUで宣言版の検証可能な公式assetが提供されたら、その対象のsource build処理と専用の前提条件、関連テストを公式asset導入へ置き換える。Rustupや、他のRustビルドでも使うMSVCリンカー設定は一括撤去しない
- **Windows arm64 の公式配布物不足**: Windows arm64 では、cosign、Trivy、1Password CLI、ShellCheckの公式 amd64 実行ファイルを互換実行する。Terraform 本体は arm64 版を使うが、署名検証用の Git GPG ヘルパーには検証済みの amd64 版を使う。対象範囲は `home/.chezmoidata.toml` の `cosign.assets.windows-arm64.emulated`、`trivy.assets.windows-arm64.emulated`、`onePassword.assets.windows-arm64.emulated`、`shellcheck.winget.platforms.windows-arm64.emulated`、`terraform.verification.windowsArm64GpgEmulated` が `true` の経路に限る。GPGの例外はTerraformの署名検証だけに使用する。各対象について、宣言版（OS packageは最低版以上）の公式 Windows arm64 配布物、または検証済みの arm64 対応 Git GPG ヘルパーが利用可能になった時点で、その対象の例外と関連テストを撤去する
- **azure-deploy のプロジェクト内 `.azure` 参照**: `home/private_dot_copilot/hooks/allowed-files.txt` は、`microsoft/azure-skills` の `azure-deploy` が直接読み書きする `.azure/deployment-plan.md` だけを Copilot Guard の拒否対象から除外する。ホームの `~/.azure` と、`azd` が内部管理する `.azure/<environment-name>/.env`、`.azure/config.json` は除外しない。PreToolUse がスキル識別子を提供し、呼び出し元を限定できるようになった場合、または上流スキルが `.azure/deployment-plan.md` を直接扱わなくなった場合は、この規則と関連テストを撤去する
- **op-ssh-sign-wsl.exe CRLF (ADR-012)**: `home/dot_local/bin/executable_op-ssh-sign-wrapper.sh.tmpl` で stdout/stderr の CR を剥がしている。1Password が WSL バイナリの改行を LF に揃えた場合、または全対応 WSL 経路で Git 2.36 以上を保証できるようになった場合は、wrapper と `.gitconfig-linux` の `program` 切替を撤去する
- **git の張り替え (ADR-020)**: `home/run_once_before_10-install-packages.sh.tmpl` の `git_unshadow` が、Codespaces と Dev Container のベースイメージが `/usr/local/bin` へソースビルドした古い git を `/usr/bin` の PPA 版へ symlink で張り替えている。ADR-020 の設定ベースフックが git 2.54 以上を要求するためである。対象イメージの `/usr/local/bin/git` がすべて 2.54 以上になったら、関数と呼び出しを撤去する（`devcontainers/base:ubuntu` は 2.55.0 で条件を満たす。Codespaces universal 5.1.5 は 2.53.0 で満たさない）
- **Azure MCP Server の sandbox 化見送り**: `sandboxMcpServers: false`（ADR-026）を維持し、Broker mode（`AZURE_MCP_ONLY_USE_BROKER_CREDENTIAL=true`）や専用 `AZURE_CONFIG_DIR` は導入していない。実装物は無く、上流の sandbox 基盤自体が未成熟なため保留している。[github/copilot-cli#3849](https://github.com/github/copilot-cli/issues/3849)（Windows sandbox 起動不可）、[#3861](https://github.com/github/copilot-cli/issues/3861)（cross-platform 分離の文書相違）、[#2112](https://github.com/github/copilot-cli/issues/2112)（MCP OAuth token の keychain 残留）のいずれかが解消したら再検討する
