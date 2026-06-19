# ADR-010: Copilot CLI の URL 包括制御は preToolUse Hook で行う

## Status

Superseded by ADR-015

ADR-015 により、本 ADR の URL allowlist Hook とネットワーク系 `--deny-tool` 補助列挙は撤去した。これらは Hook の fail-open、Hook が発火しない経路、コマンド名や URL 文字列検査の抜け道により、shell network control の境界として維持しない。

## Context

Copilot CLI v1.0.35-4 / v1.0.49 時点の実機検証で、CLI 単体では「listed 以外 deny」型の URL ホワイトリスト制御が実現できないことを確認した。`--deny-url='*'` や `--deny-url='https://*'` の wildcard 単独指定はヒットせず、機能するのは個別 domain（例 `example.com`）または prefix（`https://example.com/*`）のみ。さらに `--allow-all`（`--allow-all-urls` を含む）下では `--deny-url` / `--allow-url` 自体が無効化される。`~/.copilot/config.json` の `deniedUrls` も同様で、加えて単独ワイルドカード `"*"` は設定ファイル側で非対応、リポジトリレベル設定（`.github/copilot/settings.json`）では `deniedUrls` / `allowedUrls` キー自体がサポートされない。当時は Hook で包括的ホワイトリスト方式を実装したが、ADR-015 でこの方式を撤去した。

## Decision

URL の包括的ホワイトリスト制御は preToolUse Hook の `check_url_allowlist`（`home/private_dot_copilot/hooks/scripts/executable_copilot-guard.py:563-578`）と `home/private_dot_copilot/hooks/allowed-urls.txt` に集約する。CLI の `--deny-url` はサブエージェント（task 経由）経路で Hook が発火しない穴を埋めるための個別 domain **補助列挙**として使い、ホワイトリスト化目的では使わない。`~/.copilot/config.json` の `allowedUrls`/`deniedUrls` は `--allow-all-tools` 下で機能しないため運用で依存しない。ADR-006 の fail-open 方針（allow は出さない）を踏襲する。

## Consequences

- Hook は fail-open（exit 1 / 不正 JSON / timeout / 空出力で通過）なため、allowlist は shell network control の境界にならない
- Hook が発火しない経路やコマンド名検査の抜け道が残るため、URL allowlist Hook とネットワーク系 `--deny-tool` 補助列挙は復活させない
- 判断の前提は CLI v1.0.35-4 の挙動。アップグレード時に再検証し、shell network control の見直しは ADR-015 の sandbox policy 側で扱う
- 現時点では `allowed-urls.txt` は削除済みで URL 制御は適用していない。将来ブロック対象が発生した場合も、URL 文字列検査ではなく ADR-015 の sandbox policy で扱う
- 検証ログ: セッション 978f18e4-1610-4819-98be-6620c6d68271（A1/A15）