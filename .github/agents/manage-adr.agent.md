---
name: manage-adr
description: ADR のライフサイクル管理。作成・廃止・置換・レビュー。「ADR を作成」「ADR を廃止」「ADR を置換」「ADR をレビュー」「memory を ADR 化」「manage-adr」と言われたら使う。
---

ADR（Architecture Decision Record）のライフサイクル全体を管理する。対象は `docs/adr/`。

## パスの判定

ユーザーの意図に応じてパスを選択する:

- ADR を**会話から作りたい** → パス B
- ADR を**stored memories から作りたい** → パス B'
- ADR を**廃止したい** → パス C
- ADR を**置換したい**（新しい判断で上書き）→ パス D
- ADR を**レビューしたい**（全体の健全性確認）→ パス E

明示されない場合は直近の会話文脈から推測し、不明瞭ならユーザーに確認する。

---

## パス B: セッション会話 → ADR

1. 現在の会話コンテキストから設計判断を抽出する。session_store が使える場合は補完に使う:
   ```sql
   SELECT t.user_message, t.assistant_response
   FROM turns t JOIN sessions s ON t.session_id = s.id
   WHERE s.id = '<current_session_id>'
   ORDER BY t.turn_index;
   ```
2. 各判断に「6ヶ月テスト」を適用する:
   - 6ヶ月後に「なぜこうなっている？変えていい？」と聞かれそうか？
   - 聞かれそうな判断のみ ADR にする
3. ADR 候補をユーザーに提示し、確認を取る
4. ADR を作成する（共通手順を参照）

---

## パス B': stored memories → ADR（dotfiles 固有）

stored memories に蓄積された判断のうち、永続的で重要なものを ADR に昇格させる。

1. 関連する memories を citations 付きで一覧する（subject でフィルタすると良い）
2. 各 memory に「6ヶ月テスト」を適用する。以下は ADR にしない:
   - 一時的なワークアラウンド（上流 Issue が Close したら消えるもの）
   - プラットフォーム差分の事実記述（「X は Y では未提供」等）
   - コマンド用法やテスト手順
3. 採用候補をユーザーに提示し、確認を取る
4. ADR を作成する（共通手順を参照）
5. **memory を更新**: 元 memory の本文を `ADR-NNN を参照。<1行サマリ>` に差し替えて `store_memory` を呼ぶ。citations に ADR パスを追加する

---

## パス C: 既存 ADR の廃止（Deprecated）

対象の判断がもはや有効でなく、置き換える新しい判断もない場合。

1. `docs/adr/INDEX.md` から対象 ADR を特定する
2. 対象 ADR の **Status** を `Deprecated` に変更し、Context または Consequences に廃止理由を追記する
3. `docs/adr/INDEX.md` の Status 列を更新する
4. 変更をユーザーに提示し、確認を取る

---

## パス D: 既存 ADR の置換（Superseded）

1. `docs/adr/INDEX.md` から旧 ADR を特定する
2. 新しい ADR を作成する（共通手順を参照）
3. 旧 ADR の **Status** を `Superseded by ADR-NNN` に変更する
4. 新 ADR の Context に「ADR-MMM を置換する」旨を記載する
5. `docs/adr/INDEX.md` の両方のエントリを更新する
6. 変更をユーザーに提示し、確認を取る

---

## パス E: ADR レビュー

全 Accepted ADR の健全性を確認する。

1. `docs/adr/INDEX.md` から Status が `Accepted` の ADR を一覧する
2. 各 ADR について、言及されている構成が以下に実在するか確認する:
   - `home/`（chezmoi テンプレート）
   - `home/dot_config/mise/`（mise 設定）
   - `hooks/` および `home/private_dot_copilot/hooks/`（Copilot フック）
   - `tests/`
   - `install.sh` / `reference/`
3. 決定内容と現在のコードが矛盾していないか検証する
4. 問題が見つかった ADR について、以下を提案する:
   - 実態が変わった → パス C（Deprecated）または D（Superseded）
   - ADR が指す対象が未実装 → 問題なし
5. レビュー結果を一覧で報告する

---

## 共通: ADR 作成手順

1. `docs/adr/INDEX.md` の最大番号の次を採番する
2. `docs/adr/NNN-<kebab-case-title>.md` を作成する:
   - Status / Context / Decision / Consequences の 4 セクション
   - 30 行以下に収める
   - 言語はリポジトリ README に従う（このリポジトリでは日本語）
3. `docs/adr/INDEX.md` の一覧テーブルに追加する
4. 一時的 / 影響の小さい判断は ADR にしない
