# ADR-028: mise を撤去しツールごとの公式導入経路を使用する

## Status

Accepted

全体の設計判断の採用を記録する。実機検証の合格や全端末での撤去、清掃の完了を示すものではない。

## Context

このリポジトリでは mise を前提に、shim の symlink 化、lockfile 同期、対象プラットフォーム固定、pnpm の直接管理、公式成果物からの導入といった判断を積み重ねてきた。しかし mise は汎用ツールマネージャーであり、各ツールの公式インストール経路とは別の抽象層と状態（shim、lockfile、バージョン解決ロジック）を持ち込む。この抽象層は ADR-009/016 のように言語ツールチェイン固有の解決順序と衝突し、ADR-027 のように OS ごとの導入機構の差異を吸収するための追加判断を要求し続けてきた。

mise という共通レイヤーを維持する限り、個々のツールの公式な導入、更新、検証手順との差分を横断的に管理し続けるコストが発生し、mise 自体のバージョン管理、shim 経路、lockfile 整合性が独立した関心事として残り続ける。

[ADR-002](002-mise-shims-symlink-to-local-bin.md)、[ADR-003](003-mise-shim-exclude-pattern.md)、[ADR-013](013-mise-lockfile-sync-hook.md)、[ADR-021](021-mise-lockfile-platforms.md)、[ADR-022](022-pnpm-via-mise-not-corepack.md)、[ADR-027](027-mise-install-from-official-artifacts-per-os.md) は mise 固有の責務の撤去により Deprecated となり、旧判断の記録として保持する。

実行ファイルを単一の bin ディレクトリへ集約する方針は、SDK や付随 payload を必要とする Windows ツールには適用できない。.NET muxer は、起動された `dotnet.exe` に隣接する `host/fxr` を探索する。このため、別の SDK root にある `dotnet.exe` への symlink や hardlink、または `DOTNET_ROOT` の設定では、muxer が基準とする root の問題を解決できない。公式の Windows テストも、symlink から起動した muxer が symlink 先ではなく起動位置を基準に探索する挙動を示している（[SymbolicLinks.cs](https://github.com/dotnet/runtime/blob/79d0c463f1b55624c874a11585f7e47731e8d675/src/installer/tests/HostActivation.Tests/SymbolicLinks.cs#L336-L357)）。

Windows arm64 では、一部ツールに native な公式配布物が存在せず、独自の source build で代替すると、暗号バックエンドや依存ライブラリの制約により元の実行体との機能差が生じる場合がある。この機能差は、ツールごとに公式導入経路を優先する原則だけでは解消できない。

## Decision

mise を段階的に完全撤去する。撤去後は、ツールごとに以下の優先順位で導入経路を個別に選ぶ。

- OS/ベンダーの標準パッケージマネージャー
- 各ツールの upstream が推奨するインストーラー、スクリプト、専用バージョンマネージャー
- 検証済みの公式リリース成果物
- 言語エコシステム標準のコマンド

POSIX では、ネイティブの symlink または実体を `$HOME/.local/bin` に配置する。Windows の単体バイナリも同じディレクトリに配置する。SDK や付随 payload を必要とする Windows ツールは、公式 distribution のディレクトリ構造を専用 root に保持し、その固定されたネイティブ実行ディレクトリを既存の User PATH 設定 script へ直接登録する。single-bin 統一のために独自の投影層を設けず、公式の Windows 手順に従って SDK 配布ディレクトリを PATH へ登録する。

native な公式配布物がない Windows arm64 では、機能維持と配布物の依存関係を確認し、個別に承認された公式 x64 配布物に限り OS 標準の互換実行で使う。別のツールへ自動的に例外を広げず、具体的な対象範囲と撤去条件は[ワークアラウンド（定期チェック対象）](../../.github/copilot-instructions.md#ワークアラウンド定期チェック対象)を正本とする。

導入は、既存の chezmoi run scripts と desired declarations の枠組みで表現する。独自の runtime proxy や wrapper、汎用 manager、共通インストーラーフレームワーク、state DB、PATH fragment ファイル、広い directory junction による投影、sandbox の権限拡大は採用しない。

## Consequences

新構成ではツールごとの導入経路が公式ドキュメントに沿い、mise の shim、lockfile、バージョン解決に起因する間接的な不整合を避けられる。一方、ツール数だけ導入経路の実装と保守が個別化し、mise が担っていた単一コマンドでの一括更新と一覧の利便性は失われる。

POSIX と Windows の単体バイナリは共通の bin 配置を維持できるが、SDK 配布物を必要とする Windows ツールは専用 root と PATH 登録を必要とする。この差異を許容することで、独自の proxy、wrapper、junction 投影による複雑さと、実行時の探索規則を壊すリスクを避けられる。

互換実行を選んだ実行体は OS の互換機能に依存するため、native 配布の提供状況と例外の撤去条件を継続して確認する必要がある。

端末に残る旧 mise 由来の状態は自動削除しない。旧リンクの受け入れと移行証拠の保持は所有者保護のためであり、mise への実行時依存を意味しない。具体的な対象範囲と撤去条件は[ワークアラウンド（定期チェック対象）](../../.github/copilot-instructions.md#ワークアラウンド定期チェック対象)に集約する。
