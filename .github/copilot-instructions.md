# GitHub Copilot Instructions（リポジトリレベル）

このリポジトリは **chezmoi** と **mise** でクロスプラットフォームの dotfiles を管理している。

このファイルと `.github/agents/` はリポジトリ自身用、`home/` 配下は開発環境への配布用である。配布する GitHub Copilot 設定の対象と適用範囲は `docs/copilot.md` を参照する。

## 知識ソース

- **設計判断**: `docs/adr/INDEX.md`（形式と一覧）
- **運用ノート**: `docs/architecture.md` / `docs/operations.md` / `docs/troubleshooting.md` / `docs/copilot.md`
- **エージェント**: `.github/agents/` の `manage-adr`（ADR ライフサイクル）、`review-repo`（リポジトリ整頓）

## 記述の置き場所

指示や文書の変更時は、配布用指示のソースにある[記述の置き場所](../home/private_dot_copilot/copilot-instructions.md#記述の置き場所)を参照する。このリポジトリでの割り当ては次のとおり。

- 判断の記録は `docs/adr/`
- 手順と構造の文書は `docs/`
- 回避策の撤去条件と対象範囲は「ワークアラウンド（定期チェック対象）」へ集約する

## プラットフォーム機能契約

- 利用者向け機能は Windows/PowerShell、macOS/zsh、Linux/zsh、WSL/zsh で等価にする
- 公開関数、alias、補完、ツール導入を追加・変更するときは、全対象の実装と `tests/test_platform_parity.py` の共有テストを更新する。実装しない環境がある場合は、理由と適用範囲を同テストの契約と関連文書へ記録する

## テスト対象と実行環境

- このリポジトリは開発環境を構築・管理する。GitHub Copilot CLI や app など管理対象の環境内から管理処理を実行できることは要件にしない
- 単体テストは純粋ロジック、静的検査、小さく隔離した入出力を対象とする。OS、filesystem、process、package manager、導入済みコマンド、sandbox backend、コンテナ、ユーザープロファイルに依存する動作は、その対象環境で確認する
- 対象環境を用意できない場合は、テンプレート生成結果や構文などを静的に確認する。別環境での擬似実行を動作確認として扱わず、必要な実機検証を関連文書に記録する

## chezmoi 操作のトラップ

- `private_mise.lock` の `private_` は属性で、ターゲット名から除かれる。ソース名と配置先の `mise.lock` を区別して記す
- `chezmoi execute-template --init` の `--stdinisatty` は既定 true で、実際の stdin を見ない。非対話経路を検査するテストでは明示的に渡す。詳細は `tests/test_chezmoi_config_template.py` の `ConfigTemplateBehaviourTests` docstring

## mise 操作のトラップ

- グローバル設定の lockfile を操作する `mise lock` では **`--global`** と **`--platform`** を必ず指定する。理由と対象プラットフォームは [`docs/operations.md`](../docs/operations.md#手動操作の重要ルール) を参照する
- `lockfile = true` で `mise install` が実際にインストールすると lockfile も更新される。`[settings] lockfile_platforms` で定義した対象プラットフォームには実行中の環境が常に加わり、既存エントリは削除されない。詳細は [`docs/operations.md`](../docs/operations.md#対象プラットフォームの定義元) を参照する
- mise の backend を変更した場合は、必要に応じて `mise install --force <tool>` で再導入し、`mise ls`、`mise which`、ツールの実行で確認する。再導入に失敗したら、backend 固有の install path と原因を調べる

## プラットフォーム制約（定期チェック対象）

mise 設定を変更する際は、以下のツールの対応状況を確認し、解消されていれば条件分岐やバックエンド変更を元に戻す:

- **cargo-make**: linux/arm64 未提供（[sagiegurari/cargo-make#541](https://github.com/sagiegurari/cargo-make/issues/541)）

## ワークアラウンド（定期チェック対象）

- **GitHub Copilot sandbox の Windows mise shim 回避**: Windows ProcessContainer 内では mise shim が config、lockfile、state を読めず `uv is not a valid shim` になるため、`mise bin-paths` が返す実体ディレクトリを User PATH の先頭へ同期し、state file `~\.local\state\chezmoi-dotfiles\mise-windows-user-paths.txt` で前回分を管理する（ADR-013）。ProcessContainer 内で shim が config、lockfile、state を解決し、非対話 PowerShell tool から `jq`、`rg`、`uv` を起動できるようになったら、PATH 同期、state file、関連テストを撤去し、PATH から同期済みエントリを削除する
- **macOS Azure MCP の.NET bundle展開先**: `dot_profile.tmpl` は `DOTNET_BUNDLE_EXTRACT_BASE_DIR` が未設定の場合だけ、所有者とmode `0700` を確認したmacOS標準のユーザー専用 `TMPDIR` を設定する。上流 [microsoft/mcp#3976](https://github.com/microsoft/mcp/issues/3976) の修正が利用版に入り、macOS sandboxで環境変数の上書きなしにAzure MCPが起動すると確認できたら、設定と関連テストを撤去する
- **Visual Studio Build Tools の WinGet Configuration v2 昇格**: Build Tools 本体は通常権限の `WinGetPackage`、C++ ワークロードは `vswhere.exe` で MSVC の `link.exe` を検査して必要時だけ対話型セッションから Visual Studio Installer を UAC 昇格する `PSDscResources/Script` で管理する。通常権限から `securityContext: elevated` のユニットを実行しても `0x800706BA` が発生せず、管理者 PowerShellでも `WinGetPackage` のカタログ接続が成功するようになったら、公式の `Microsoft.VisualStudio.DSC/VSComponents` 構成へ戻す
- **op-ssh-sign-wsl.exe の CRLF（ADR-012）**: WSL 用 wrapper が stdout と stderr の CR を除去する。1Password が LF を出力するか、全対応 WSL で Git 2.36 以上を保証できたら wrapper と Git 設定の切替を撤去する
- **WinGet ポータブルパッケージのリンクと RedirectionGuard**: 通常権限の WinGet が `%LOCALAPPDATA%\Microsoft\WinGet\Links` に作るシンボリックリンクは、RedirectionGuard が有効なプロセス（Command Palette など一部のパッケージアプリと、そこから起動した Windows Terminal や PowerShell）から辿れず、error 448 で起動に失敗する（[microsoft/winget-cli#6454](https://github.com/microsoft/winget-cli/issues/6454)）。chezmoi など `Links` にリンクを作るパッケージを通常権限で導入・更新した後は、管理者 PowerShell で該当リンクを削除し、同じターゲットへ作り直す。mise で管理できるツールは WinGet で重複導入しない。上流で修正され、通常権限の WinGet が作ったリンクを Command Palette から起動した Windows Terminal で実行できるようになったら、この手順を撤去する
- **Command Palette から起動した Terminal への RedirectionGuard 継承**: PowerToys Command Palette は RedirectionGuard が有効な状態で起動し、そこから起動した Windows Terminal と子プロセスへ保護が継承される。保護下では通常権限で作られたジャンクションを辿れず、mise の dotnet（shared モード）、rustup、uv などが error 448 で失敗する（[microsoft/PowerToys#52355](https://github.com/microsoft/PowerToys/issues/52355)）。Command Palette のブックマークに `explorer.exe shell:AppsFolder\Microsoft.WindowsTerminal_8wekyb3d8bbwe!App` を登録し、Terminal はこのブックマークから起動する。既存の Explorer が起動を引き継ぐため、保護が継承されない。ブックマークは手動設定であり、chezmoi では管理しない。Command Palette から直接起動した Terminal の子プロセスで RedirectionGuard が無効になったら、ブックマークを削除する
