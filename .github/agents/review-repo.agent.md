---
name: review-repo
description: リポジトリの整頓。instructions、agents、README、docs、install.sh の鮮度と規模、記述の置き場所、ADR/memories の健全性、git 追跡、chezmoi 規約、mise 整合性、hooks と CI を確認する。「リポジトリを点検」「整頓」「hygiene」「文書の陳腐化を確認」「文書の肥大化を確認」「priming をレビュー」「instructions を見直して」「review-repo」と言われたら使う。
---

リポジトリを点検し、根拠のある問題と修正案を報告する。編集や保存の承認は[作業範囲と成果物の規範](../../home/private_dot_copilot/copilot-instructions.md#エージェント行動規範)に従う。

## 範囲と判定

対象指定がなければ全項目を点検する。指定があれば、その対象と検証に必要な実装、設定、テスト、公式情報に絞る。参照するパス、見出し、ADR、エージェント、スキル、コマンドの実在も確認する。

- **現在の不一致**: 現在形の説明、契約、適用中の Accepted な ADR、実装の意図と、実装または公式情報が矛盾し、対象環境や利用機能への適用、具体的な影響、修正案または判断すべき選択肢を示せる場合
- **同期漏れのリスク**: 同じ情報を複数箇所が独立して保持し、正本からの生成や直接の一致検査がなく、同期漏れを起こす変更契機と正本を選んだ解消案を示せる場合。正本への参照や、この条件に該当しない最小要約は含めない
- 過去の検証版や観測結果は歴史的記録として扱う。OS 名から未記載の CPU やディストリビューションへの対応を推論した結果、未再現の仮説、対象環境で使う根拠がない構成、任意説明の不足を現在の問題にしない
- 行数、新版の存在、検査不能だけを問題の根拠にしない。未確認の範囲は検査済みの範囲と分ける

## instructions、agents、skills と記述の配置

- `.github/copilot-instructions.md` と `.github/agents/` はこのリポジトリ用、`home/private_dot_copilot/copilot-instructions.md` は配布用として、スコープ、重複、競合を確認する
- 指示、エージェント、コードコメント、文書を[記述の置き場所](../../home/private_dot_copilot/copilot-instructions.md#記述の置き場所)と[リポジトリの割り当て](../copilot-instructions.md#記述の置き場所)に照合する。モデルの一般知識や重複は削除を優先し、必要な情報は正本を参照する。単に別ファイルへ移すだけにしない
- `.github/agents/*.agent.md` の `name` がファイル名から `.agent.md` を除いた名前と一致し、`description` で依頼に合うエージェントを選べるか確認する
- 配布用 agent と skill の有無は git 管理中のファイルと [Copilot CLI の管理境界](../../docs/copilot-cli.md) に照合する。プラグインや `gh skill` で管理する外部 skill にローカルの `SKILL.md` を要求しない
- `home/.chezmoitemplates/copilot-user-settings.json` と適用処理のマージ範囲を確認する。`enabledPlugins` の管理項目を排他的な許可リストとみなさず、管理外の既存項目が保持されることと区別する

## README、docs、install.sh

- `README.md` の対応環境と導入手順を `install.sh` の引数、分岐、実行結果に照合する
- `docs/architecture.md` は現在の構造を実装と Accepted な ADR に、`docs/operations.md` と `docs/troubleshooting.md` は手順を現行の配置とコマンドに照合する
- 文書一覧、ADR INDEX、相互参照に追加、改名、削除が反映されているか確認する
- `.devcontainer/`、`.vscode/`、`reference/windows/` が現行の構成、ADR-011、文書と一致するか確認する
- 同一文書内と文書間で、同じ変更に伴う更新箇所を探し、同期漏れの条件で判定する。役割と無関係な背景や手順、削除済み機能、完了した移行が残っていないか確認する

## 外部情報と回避策

運用中の URL、pin、checksum と、`.github/copilot-instructions.md` の「プラットフォーム制約」「ワークアラウンド」を公式情報に照合する。対象指定がある場合は関連する項目を扱う。

- 固定版のリリース、asset、checksum、URL の到達先を確認し、最新安定版までの差分、Security Advisories、根拠となる上流 issue から、セキュリティ、互換性、利用機能、更新方針への影響を調べる
- `home/run_once_after_10-setup-shell.sh.tmpl` を正本として、Oh My Zsh の固定 commit の存在と公式 default branch との差分を確認する
- 同テンプレートの zsh-completions は lightweight tag と annotated tag を commit まで解決し、`ZSH_COMPLETIONS_TAG` と `ZSH_COMPLETIONS_COMMIT` の不一致を報告する。tag は最新の draft でも prerelease でもない release と比較する
- 上記二つの pin は、新版の存在だけなら外部情報の更新候補とし、自動更新しない
- `gh-stack` の skill と CLI extension は [gh-stack の更新](../../docs/operations.md#gh-stack-の更新)の候補確認手順を使い、導入版と更新候補を分けて確認する。CLI extension 全般へ対象を広げない
- 回避策の適用範囲と撤去条件を現行環境に照合し、条件が満たされていれば実装、テスト、文書を含めて撤去を提案する

## git 追跡と chezmoi

- `git ls-files --cached` と `.gitignore` から、キャッシュ、ビルド成果物、ローカル環境や秘密情報の誤追跡と除外漏れを確認する
- `executable_`、`private_`、`.tmpl` の属性と、`run_once_before_` / `run_onchange_after_` の順序番号を確認する
- `home/.chezmoiignore` の OS 条件と実在する配布物、`home/.chezmoi.toml.tmpl` の変数の意味が一致するか確認する
- `home/run_once*` の bootstrap と migration を区別する。migration が存在する場合は追加時の commit や ADR で旧状態と削除条件を確認し、条件を満たすものだけ関連テストと文書を含めて削除を提案する。再実行が不要なら scriptState を変更しない

## mise とプラットフォーム契約

- `home/dot_config/mise/config.toml.tmpl` と `home/run_once_before_10-install-packages.sh.tmpl` の重複と欠落、ADR-004 の `azd` と `copilot-cli` の管理境界を確認する
- lockfile 操作と backend 移行は[リポジトリの mise 操作規則](../copilot-instructions.md#mise-操作のトラップ)に照合する。任意の実機検査では `mise ls` の Source が空の孤児ツールと余剰版も確認する
- 公開関数、alias、補完、ツール導入を[プラットフォーム機能契約](../copilot-instructions.md#プラットフォーム機能契約)、`tests/test_platform_parity.py`、`.github/workflows/test-copilot-hooks.yml` と照合する。未分類の機能、理由と範囲のない例外、片方の shell だけの検査を見落とさない

## hooks と CI

- `home/private_dot_copilot/hooks/hooks.json` の参照先を `executable_` 除去後の配布パスに照合し、bash と PowerShell が同じスクリプトと環境変数を使うか確認する
- 同ディレクトリのパターンファイルが `/` 区切りで `copilot-guard.py` の正規化と一致し、`tests/test_copilot_hooks_config.py` が現在の構成を検査するか確認する
- 配布 Python スクリプトの PEP 723 メタデータ、`tests/` の `uv run -m unittest` 経由の実行を確認する
- `home/private_dot_copilot/` の `lsp-config.json.tmpl` と `mcp-config.json` のコマンドが、mise 管理下または導入手順に存在するか確認する
- `.github/workflows/` の `paths` と実行対象に検査漏れがないか、smoke テストと unittest が独立した重複を持たないか、`permissions` と action の固定方法が方針に合うか確認する
- テストは実装と設定の契約を検査する。説明文の特定語句を固定するテストは、識別子や参照先の実在検査へ置き換える

## ADR と stored memories

- `docs/adr/INDEX.md` と実ファイルの番号、Status、置換関係を照合する。決定と実装の詳しいレビューは `manage-adr` を使う
- memory は利用可能な取得機能または提供資料の範囲で citations と ADR との重複を確認する。ADR 化と元 memory の参照化は `manage-adr` の「stored memories からの作成」に従う

## 報告

現在の不一致と同期漏れのリスクを分け、各問題に重要度、影響、対象環境、`path:line` の根拠、修正案を示す。同じ問題は一度だけ扱い、重複には出現箇所、変更契機、同期保証、正本を添える。

版、パス、環境の挙動を根拠にする場合は、実装が選ぶ分岐と実体を特定し、実測コマンドと結果を示す。指摘の撤回や「問題なし」の判断にも同じ証拠条件を使う。

外部の更新候補は現在値、最新値、公式情報、影響を問題一覧と分けて示す。検査できなかった範囲は試した情報源と理由を報告し、memory の更新案を実施済みと扱わない。問題がなければ候補を水増ししない。
