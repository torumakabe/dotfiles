---
name: manage-adr
description: ADR のライフサイクル管理。作成・廃止・置換・レビュー。「ADR を作成」「ADR を廃止」「ADR を置換」「ADR をレビュー」「memory を ADR 化」「manage-adr」と言われたら使う。
---

`docs/adr/` の作成、廃止、置換、レビューを扱う。採用基準、形式、状態は [INDEX](../../docs/adr/INDEX.md) に従い、作成や状態変更を一覧へ反映する。

記述の配置は[共通規範](../../home/private_dot_copilot/copilot-instructions.md#記述の置き場所)と[リポジトリの割り当て](../copilot-instructions.md#記述の置き場所)、承認は[作業範囲と成果物の規範](../../home/private_dot_copilot/copilot-instructions.md#エージェント行動規範)に従う。

## 作成

- 会話または提供資料から設計判断と根拠を抽出する。利用可能ならセッション履歴で補完する
- 採用基準を満たす判断を `docs/adr/NNN-<kebab-case-title>.md` に記録する。番号は INDEX の最大番号の次とする

### stored memories からの作成

- 取得可能な関連 memory と citations、またはユーザー提供資料を使う。一時的な回避策、プラットフォーム差分の事実、操作手順だけを ADR にしない
- ADR 化後は元 memory を ADR 参照と短い要約へ置き換え、citation に ADR パスを追加する。`store_memory` などの更新機能が利用でき、更新が承認範囲に含まれる場合だけ実行する
- 一覧取得や更新ができなければ、提供資料で進めた範囲と未実施の操作を報告する。更新案の提示を実際の memory 更新として扱わない

## 廃止と置換

- **廃止**: 判断が無効になり後継がない場合は `Deprecated` とし、Context または Consequences に廃止理由を残す
- **置換**: 後継 ADR を作成し、旧 ADR を `Superseded by ADR-NNN` にする。新 ADR の Context に置換元を記載し、INDEX の両方のエントリを更新する

## レビュー

対象指定がなければ全 Accepted ADR を対象とする。決定の適用条件を確認し、関連する `home/`、`tests/`、`install.sh`、`reference/` の実装と照合する。

- 将来の適用時期や段階的導入が明記され、まだ適用条件を満たさない部分は、未実装という理由だけで不一致にしない
- 現在適用される Accepted な決定の実装が欠けていれば、不一致として報告する。未実装を一律に免除しない
- 実態が変わった場合は、実装を決定に合わせるか、判断を廃止または置換するかを根拠付きで提案する
