# ADR-010: Copilot CLI の URL 包括制御は preToolUse Hook で行う

## Status

Accepted

## Context

Copilot CLI v1.0.35-4 / v1.0.49 時点の実機検証で、CLI 単体では「listed 以外 deny」型の URL ホワイトリスト制御が実現できないことを確認した。`--deny-url='*'` や `--deny-url='https://*'` の wildcard 単独指定はヒットせず、機能するのは個別 domain（例 `example.com`）または prefix（`https://example.com/*`）のみ。さらに `--allow-all`（`--allow-all-urls` を含む）下では `--deny-url` / `--allow-url` 自体が無効化される。`~/.copilot/config.json` の `deniedUrls` も同様で、加えて単独ワイルドカード `"*"` は設定ファイル側で非対応、リポジトリレベル設定（`.github/copilot/settings.json`）では `deniedUrls` / `allowedUrls` キー自体がサポートされない。`copilot --autopilot` のような Autopilot 運用や `--allow-all` 系オプションを伴う運用では、包括的ホワイトリスト方式は Hook でしか実現できない（`--deny-tool 'url(...)'` は `--allow-all` 下でも優先されるが、個別列挙のため包括制御には向かない）。

## Decision

URL の包括的ホワイトリスト制御は preToolUse Hook の `check_url_allowlist`（`home/private_dot_copilot/hooks/scripts/executable_copilot-guard.py:563-578`）と `home/private_dot_copilot/hooks/allowed-urls.txt` に集約する。CLI の `--deny-url` はサブエージェント（task 経由）経路で Hook が発火しない穴を埋めるための個別 domain **補助列挙**として使い、ホワイトリスト化目的では使わない。`~/.copilot/config.json` の `allowedUrls`/`deniedUrls` は `--allow-all-tools` 下で機能しないため運用で依存しない。ADR-006 の fail-open 方針（allow は出さない）を踏襲する。

## Consequences

- Hook は fail-open（exit 1 / 不正 JSON / timeout / 空出力で通過）なため、allowlist は「うっかり外部アクセス防止」レベルの保険で完全隔離ではない
- サブエージェント経路は Hook 未発火。危険 URL は CLI `--deny-url` で個別列挙が必須
- 判断の前提は CLI v1.0.35-4 の挙動。アップグレード時に再検証、CLI が wildcard `--deny-url='*'` をサポートしたら allowlist 簡素化／撤去を検討する（`review-repo` の定期チェック対象）
- 現時点では `allowed-urls.txt` は空（全行コメントアウト）で URL 制御は適用していない。本 ADR は将来ブロック対象が発生した際の実装先を定めるもの
- 検証ログ: セッション 978f18e4-1610-4819-98be-6620c6d68271（A1/A15）