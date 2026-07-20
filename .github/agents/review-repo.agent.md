---
name: review-repo
description: リポジトリの整頓。instructions の鮮度、ADR/memories の健全性、git 追跡、chezmoi 規約、mise 整合性を確認する。「リポジトリを点検」「整頓」「hygiene」「priming をレビュー」「instructions を見直して」「review-repo」と言われたら使う。
---

リポジトリ全体を点検し、問題を報告・修正する。

## 原則

- `copilot-instructions.md` はリポジトリ／ユーザーレベルどちらも **50 行以内** を目安
- 詳細知識はユーザーレベルスキル（chezmoi ソースでは `home/private_dot_copilot/skills/`）、設計判断は ADR（`docs/adr/`）に分離する
- 不要になった記述の削除も提案する（追加だけでなく）
- 修正は **ユーザー承認後** に行う

## 対象ファイル

- **リポジトリレベル:** `.github/copilot-instructions.md`
- **ユーザーレベル（chezmoi ソース）:** `home/private_dot_copilot/copilot-instructions.md`

どちらを対象とするか指定がない場合はユーザーに確認する。

## チェック項目

### 1. copilot-instructions.md の整合性

#### 1a. サイズ
- 総行数を計測し、50 行超なら圧縮を提案する

#### 1b. 圧縮基準レビュー（旧 compact-copilot-instructions スキル相当）

| ID | 基準 | アクション |
|----|------|-----------|
| C1 | デフォルト動作との重複 | 削除を提案 |
| C2 | ルール間の冗長 | 統合を提案 |
| C3 | 説明の冗長 | 短縮案を提示 |
| C4 | 効果の薄いルール | ユーザー判断に委ねる |
| C5 | スコープ違い（ユーザー ↔ リポジトリ） | 移動を提案 |
| C6 | ADR 化すべき永続判断が混ざっている | `manage-adr` のパス B/B' への誘導 |

#### 1c. 参照の実在
- 「ディレクトリ構造」「知識ソース」「規約」「エージェント」節に出てくるパスが実在するか
- 参照している ADR 番号・エージェント名が存在するか

### 2. git 追跡の整頓

```bash
git ls-files --cached | grep -E '\.(whl|pyc|pyo)$|__pycache__|\.ruff_cache|\.DS_Store|\.env$|\.venv/'
```

検出されたファイルがあれば `git rm --cached` を提案する。

### 3. chezmoi 命名規約

`home/` 配下で、chezmoi プレフィックスが期待される用途と揃っているか:

- 実行可能スクリプト → `executable_` プレフィックス
- 機微ファイル（`.copilot` 内の設定、認証系）→ `private_` プレフィックス
- テンプレート処理が必要なファイル → `.tmpl` 拡張子
- `run_once_before_` / `run_onchange_after_` の順序番号が衝突していないか

### 4. run_once のライフサイクル

1. `home/run_once*` を列挙し、各スクリプトを次のいずれかに分類する:
   - **bootstrap**: 新規端末の初期設定に必要。既存端末で実行済みという理由では削除しない
   - **migration**: 過去の状態を新しい状態へ一度だけ移行する
2. migration について、追加時の commit、関連 ADR、スクリプト内コメントから、対象となる旧状態と削除条件を確認する
3. 削除条件が成立したことを設定、lockfile、対象ツールの現行仕様で確認する。判断根拠を示せない migration は削除せず、⚠️ として報告する
4. 不要と判断した migration は、参照するテストと文書を含めた削除案を提示する。chezmoi の scriptState は、再実行が必要な場合を除いて変更しない
5. 新しい migration に対象となる旧状態と機械的に確認できる削除条件が記載されていなければ、追加前に補足を求める

### 5. mise 設定と install-packages の整合

#### 5a. ソース照合（静的）

- `home/dot_config/mise/config.toml.tmpl` に列挙されているツールと、`home/run_once_before_10-install-packages.sh.tmpl` で OS 別に入れているツールに重複や欠落がないか
- ADR-004 対象（`azd`, `copilot-cli`）は **mise 外** で定義されていることを確認
- `mise lock` 実行時は `--global --platform` が指定される運用になっているか（`dot_zshrc.tmpl` / `PowerShell_profile.ps1.tmpl` の関数）

#### 5b. 実機 mise ドリフト検査（ランタイム／任意）

ソース照合ではなく、**このコマンドを実行した実機**の mise 状態を点検する。
結果は環境依存で、修正は実機のみを変更し git diff は出ない点に留意する。

- `mise ls` を実行し、**Source 列が空**のエントリ（どの config にも紐づかない）を洗い出す:
  - **孤児ツール**（config.toml に存在しないツール）→ ADR-004 対象（`copilot`/`azd` 等）が mise 経由で残っていないか特に注意。`mise uninstall --all <tool>` を提案
  - **宣言ツールの余剰バージョン**（現行版以外）→ `mise prune --tools` を提案
- 修正提案は他項目と同じくユーザー承認後に実施する

### 6. Python スクリプトの uv 統一（ADR-007）

- `hooks/`・`home/private_dot_copilot/hooks/scripts/`・`tests/` の Python スクリプトに PEP 723 インラインメタデータ（`# /// script`）があるか
- 同領域に `.sh` / `.ps1` / `.bat` がないか（あれば Python への統一を提案）

### 7. ADR 健全性サマリ

- `docs/adr/INDEX.md` を読み、`Accepted` な ADR の数と最新番号を確認
- 詳細な照合が必要な場合は `manage-adr` のパス E を提案

### 8. stored memories のドリフト検出

- 関連する stored memories を citations 付きで確認
- citations にあるパス（`home/...`, `docs/...`, `tests/...`）が実在するか
- ADR 化済みの内容を重複して保持している memory があれば「ADR-NNN 参照」形式への更新を提案（`manage-adr` パス B' に誘導）

### 9. スキル整合性

- `home/private_dot_copilot/skills/` 内の各ディレクトリに `SKILL.md` が存在するか
- `copilot-instructions.md` で参照しているスキルが実在するか

## 出力

1. 各チェック項目の結果を一覧で報告（✅ / ⚠️ / ❌）
2. 問題がある項目について具体的な修正案を提示
3. ユーザー承認を得てから編集を適用

<!-- TODO: Copilot CLI にメモリの list/get/delete 機能が実装されたら（github/copilot-cli#2278）、
     チェック項目 7 を拡張してメモリの一覧・削除まで自動化する。 -->
