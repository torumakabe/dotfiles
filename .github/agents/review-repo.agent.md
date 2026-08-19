---
name: review-repo
description: リポジトリの整頓。instructions、agents、README、docs、install.sh の鮮度と規模、記述の置き場所、ADR/memories の健全性、git 追跡、chezmoi 規約、mise 整合性、hooks と CI を確認する。「リポジトリを点検」「整頓」「hygiene」「文書の陳腐化を確認」「文書の肥大化を確認」「priming をレビュー」「instructions を見直して」「review-repo」と言われたら使う。
---

リポジトリ全体を点検し、根拠のある問題と修正案を報告する。修正はユーザー承認後に行う。

## 原則

- 調査範囲を狭めず、問題として報告する条件を厳しくする
- 確認済みの事実、上流情報、未確認の範囲を区別する
- 同じ問題を複数の項目が検出した場合は、最も具体的な項目で一度だけ報告する
- 行数や新版の存在だけで問題と判定しない
- 不要な記述の削除と正本への参照を、追記より先に検討する

## 対象

- `.github/copilot-instructions.md`
- `home/private_dot_copilot/copilot-instructions.md`
- `.github/agents/*.agent.md`
- `README.md`
- `docs/**/*.md`
- `install.sh`
- コードコメント
- 判定に必要な実装、設定、テスト、CI、ADR、上流の公式情報

対象指定がなければ全項目を点検する。特定の対象が指定された場合は、その記述を検証するために必要な関連ファイルも確認する。

全対象に共通して、記載されたパス、見出しアンカー、ADR番号、エージェント、スキル、コマンドの参照先が実在するかを検証する。

## 報告する問題

現在の不一致は、次をすべて満たす場合だけ報告する。

1. 現在形の説明、明示的な契約、Accepted な ADR、実装の意図を特定できる
2. 実装または公式情報と一致しない
3. このリポジトリの対象環境または利用機能へ適用される
4. 誤動作、誤誘導、保守漏れ、脆弱性などの影響を説明できる
5. 実行可能な修正案または判断すべき選択肢を示せる

現在は一致していても、同じ値、手順、制約、回避策、不変条件を複数箇所が独立して保持している場合は、次をすべて満たせば同期漏れのリスクとして報告する。

1. 各記述が正本への参照ではなく、単独で更新対象となる
2. 文書が正本から生成されず、記述間の一致を直接検査するテストもない
3. 更新時に同期漏れが生じる具体的な変更契機を示せる
4. 正本を選び、他を削除、短縮、参照置換、またはドリフトテストで保護できる

次は、それだけでは問題にしない。

- OS 名から、明記していない CPU やディストリビューションへの対応を推論した結果
- 過去の検証時点、検証版、当時の観測結果
- 対象環境で使う根拠がない構成、再現していない仮説、任意説明の不足
- ネットワークやツールの制約で検査できなかったこと
- 役割上必要な最小要約。上記の同期漏れ条件を満たさない場合に限る

## チェック項目

### 1. instructions、agents、skills

- instructions の各ファイルを読み、重複、他の層と競合する記述、低価値な説明を特定する。特定できた場合だけ、効果を維持したまま圧縮する案を示す。行数は精読の優先順位を決める目安に使い（50行超を先に読む）、それだけを根拠に圧縮を提案しない。あわせて次を確認する
  - ユーザーとリポジトリのスコープ違いを移動
  - 永続的な設計判断は `manage-adr` のパス B/B' へ誘導
- `.github/agents/*.agent.md` の frontmatter に `name` と `description` があり、`name` がファイル名と一致するか確認する
- `home/private_dot_copilot/skills/` の各ディレクトリに `SKILL.md` があるか確認する

### 2. `README.md`、`docs/`、`install.sh`

#### 役割

層ごとの役割は項目3「記述の置き場所」で扱う。ここでは個々の対象の役割だけを示す。

| 対象 | 役割 |
|------|------|
| `README.md` | 対応環境、導入、日常的な入口、詳細文書への導線 |
| `docs/architecture.md` | 現在の構造と構成要素の関係 |
| `docs/operations.md` | リポジトリ固有の保守と更新手順 |
| `docs/troubleshooting.md` | 症状、確認方法、復旧手順 |
| `docs/copilot-cli.md` | Copilot CLI の管理境界と運用 |
| `docs/adr/` | 判断の記録。状態と置換関係を含む |
| `install.sh` | POSIX 環境で chezmoi を導入し、dotfiles を適用する処理 |

表にない文書は、冒頭の目的、内容、参照元から役割を特定する。

#### 陳腐化

- コマンド、パス、環境変数、対応環境、導入元を実装と照合する
- README の導入手順を `install.sh` の引数、分岐、実行結果と照合する
- architecture の現在形の説明を実装と Accepted な ADR に照合する
- operations と troubleshooting の手順が現行の配置とコマンドで実行できるか確認する
- 文書一覧、ADR INDEX、相互参照へ追加、改名、削除が反映されているか確認する
- `.devcontainer/`、`.vscode/`、`reference/windows/` の資材が現行の構成、ADR-011、文書の説明と一致するか確認する

#### 外部情報

運用中の外部 URL、pin、checksum、上流制約、回避策を公式情報と照合する。`.github/copilot-instructions.md` の「プラットフォーム制約」と「ワークアラウンド」は全項目を対象とする。

- 固定版のリリース、対象asset、公式checksumを確認する
- 固定版から最新安定版までの compare view と changelog を確認し、セキュリティ、互換性、利用機能に関係する差分だけを詳しく調べる
- `home/run_once_after_10-setup-shell.sh.tmpl` の値を正本として、Oh My Zsh は固定commitの存在を確認し、公式default branchと比較する。新しいcommitの存在だけなら外部情報の更新候補として扱い、現在の不一致や自動修正の対象にしない
- 同じテンプレートのzsh-completionsは、lightweight tagとannotated tagの両方をcommitまで解決し、`ZSH_COMPLETIONS_TAG`が`ZSH_COMPLETIONS_COMMIT`と一致することを必須とする。不一致は現在の不一致として報告する。TAGを最新のdraftでもprereleaseでもないreleaseと比較し、新しいreleaseは外部情報の更新候補として扱う。どちらのpinも自動更新しない
- 公式 skill と対応する CLI extension を組み合わせる機能は、実機の導入版と上流の更新を区別して確認する。現在は `gh-stack` を対象とし、`gh skill update gh-stack --dry-run` と `gh extension upgrade gh-stack --dry-run` で候補を確認する。GitHub CLI extension 全般へ対象を広げない
- GitHub Security Advisories と、根拠としている上流issueの状態を確認する
- 外部URLはリダイレクト後の到達先と記述内容を確認する
- 記述された前提（版、対象イメージ、経路、責任範囲）が現在も成立するか確認する
- 版やパスを根拠にするときは、実装が判定に使うパスと分岐を特定し、その実体を測る。同名のコマンドが複数あれば、どれが選ばれるかまで確認する
- 新版の存在だけでは問題にしない。脆弱性、非互換、利用機能への修正、更新方針との不一致がある場合に報告する
- 撤去条件が満たされた回避策は、撤去対象の実装、テスト、文書を列挙して撤去を提案する
- 取得失敗は公式APIなど別の公式経路で再確認する

#### 重複と肥大化

文言の一致だけでなく、同じ変更で更新される情報を同一文書内と文書間で探す。

- バージョン、対応環境一覧、コマンド列、パス、環境変数、制約、回避策、不変条件を抽出し、全出現箇所を確認する
- 実装、テスト、ADR、専門文書から正本を特定する
- 独立したコピーは、上記の同期漏れ条件で判定する
- 同一文書内で同じ不変条件や論点を繰り返し、更新箇所や読者負荷を増やしていないか確認する
- 役割と関係しない背景、判断、手順、復旧説明が混在していないか確認する
- 削除済みの機能、完了した移行、不要になった回避策が残っていないか確認する

行数は調査の入口に限り、それだけを根拠に分割や削除を提案しない。

### 3. 記述の置き場所

コードコメント、`docs/`、`docs/adr/` の内容を「記述の置き場所」の規範と、`.github/copilot-instructions.md` の割り当てへ照合する。層をまたぐ重複は同期漏れのリスクとして扱い、正本と削除案を示す。コメントの削除案では、削除後にコードと参照先だけで意図を追えるかを確認する。

### 4. git 追跡と `.gitignore`

`git ls-files --cached` から、`.whl`、`.pyc`、`.pyo`、`__pycache__`、`.ruff_cache`、`.DS_Store`、`.env`、`.venv` を抽出する。検出時は `git rm --cached` を提案する。あわせて `.gitignore` が同じ対象を除外しているか、実在しない対象だけを列挙していないかを確認する。

### 5. chezmoi 命名規約と配布制御

命名:

- 実行可能スクリプトは `executable_`
- 機微ファイルは `private_`
- テンプレート処理するファイルは `.tmpl`
- `run_once_before_` と `run_onchange_after_` の順序番号に衝突がない

配布制御:

- `home/.chezmoiignore` の各条件が実在するファイルと対応し、OS 固有ファイルが対象外 OS で ignore されるか
- `home/.chezmoiremove` の各エントリに、過去の配布物という根拠があるか
- `home/.chezmoi.toml.tmpl` が定義する変数を、テンプレートと ignore 条件が同じ意味で使うか

### 6. run_once のライフサイクル

1. `home/run_once*` を bootstrap または migration に分類する
2. migration は追加時のcommit、ADR、コメントから旧状態と削除条件を確認する
3. 削除条件を設定、lockfile、現行仕様で確認する。根拠を示せなければ削除しない
4. 不要なmigrationは関連テストと文書を含めて削除を提案する。再実行が不要なら chezmoi の scriptState は変更しない
5. 新しいmigrationに旧状態と機械的な削除条件がなければ補足を求める

### 7. mise と install-packages

- `home/dot_config/mise/config.toml.tmpl` と `home/run_once_before_10-install-packages.sh.tmpl` の重複と欠落を確認する
- ADR-004対象の `azd` と `copilot-cli` が mise 外にあるか確認する
- `mise lock` の運用が `--global --platform` を指定するか確認する
- 任意の実機検査では `mise ls` の Source が空の孤児ツールと余剰版を確認し、`mise uninstall --all` または `mise prune --tools` を提案する

### 8. プラットフォーム機能等価性

- 公開関数、alias、補完、ツール導入を Windows/PowerShell、macOS/zsh、Linux/zsh、WSL/zsh で確認する
- 未分類の公開機能、理由と範囲のない例外、片方のshellだけを検査するテストを問題として報告する
- `tests/test_platform_parity.py` と `.github/workflows/test-copilot-hooks.yml` が実装と契約を検査するか確認する

### 9. Python と uv

- `home/private_dot_copilot/hooks/scripts/` の配布スクリプトに PEP 723 メタデータがあるか確認する
- `tests/` は `uv run -m unittest ...` で実行されるか確認する

### 10. Copilot hooks 構成

- `hooks.json` が参照するスクリプトが、`executable_` を除いたパスで実在するか
- bash と powershell の起動行が同じスクリプトと環境変数を指すか
- `ask-files.txt` と `blocked-files.txt` のパターンが `/` 区切りで、`copilot-guard.py` の正規化と一致するか
- `tests/test_copilot_hooks_config.py` が現在の hooks.json の構成を検査するか
- `lsp-config.json` と `mcp-config.json` が参照するコマンドが、mise 管理下または導入手順に存在するか

### 11. CI ワークフロー

- `.github/workflows/` の `paths` フィルタが、検査対象の変更を取りこぼさないか
- 追加されたテストが実行対象に含まれるか
- ワークフロー内の smoke テストと `tests/` の unittest が同じ検査を独立に保持していないか
- `permissions` が必要最小か。action の参照が固定方針と一致するか

### 12. ADR と stored memories

- `docs/adr/INDEX.md` の一覧表と `docs/adr/` の実ファイルで、番号と Status が一致するか
- 関連memoryのcitation先が実在するか
- ADR化済みの内容を保持するmemoryはADR参照への更新を提案し、`manage-adr` のパス B' へ誘導する
- 詳細な整合性レビューは `manage-adr` のパス E を使う

## 出力

1. ❌ 現在の不一致と ⚠️ 同期漏れのリスクを分ける
2. 各問題に重要度、影響、対象環境、`path:line` の根拠、修正案を示す
3. 重複には全出現箇所、変更契機、現在の同期保証、推奨する正本を示す
4. 外部情報は問題一覧と分け、現在値、最新値、公式情報、リポジトリへの影響を示す
5. 必須検査を完了できなかった場合だけ、試した情報源と理由を検査範囲として示す
6. 問題がなければ候補を水増しせず「問題なし」と報告する
7. 版、パス、環境の挙動を根拠とする指摘には `実測: <コマンド> → <結果>` を添える。指摘の撤回と「問題なし」の判断にも同じ証跡を求める

<!-- TODO: Copilot CLI にメモリの list/get/delete 機能が実装されたら（github/copilot-cli#2278）、
     stored memories の一覧・削除まで自動化する。 -->
