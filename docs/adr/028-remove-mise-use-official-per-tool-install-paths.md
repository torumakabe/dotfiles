# ADR-028: mise を撤去しツールごとの公式導入経路を使用する

## Status

Proposed

## Context

ADR-002/003/013/021/022/027 は mise を前提に、shim の symlink 化、lockfile 同期、対象プラットフォーム固定、pnpm の直接管理、公式成果物からの導入といった判断を積み重ねてきた。しかし mise は汎用ツールマネージャーであり、各ツールの公式インストール経路とは別の抽象層・状態（shim、lockfile、バージョン解決ロジック）を持ち込む。この抽象層は ADR-009/016 のように言語ツールチェイン固有の解決順序と衝突し、ADR-027 のように OS ごとの導入機構の差異を吸収するための追加判断を要求し続けてきた。

mise という共通レイヤーを維持する限り、個々のツールの公式な導入・更新・検証手順との差分を横断的に管理し続けるコストが発生し、mise 自体のバージョン管理・shim 経路・lockfile 整合性が独立した関心事として残り続ける。

実行ファイルを単一の bin ディレクトリへ集約する方針は、SDK や付随 payload を必要とする Windows ツールには適用できない。.NET muxer は、起動された `dotnet.exe` に隣接する `host/fxr` を探索する。このため、別の SDK root にある `dotnet.exe` への symlink や hardlink、または `DOTNET_ROOT` の設定では、muxer が基準とする root の問題を解決できない。公式の Windows テストも、symlink から起動した muxer が symlink 先ではなく起動位置を基準に探索する挙動を示している（[SymbolicLinks.cs](https://github.com/dotnet/runtime/blob/79d0c463f1b55624c874a11585f7e47731e8d675/src/installer/tests/HostActivation.Tests/SymbolicLinks.cs#L336-L357)）。

## Decision

mise を段階的に完全撤去する。撤去後は、ツールごとに以下の優先順位で導入経路を個別に選ぶ。

- OS/ベンダーの標準パッケージマネージャー
- 各ツールの upstream が推奨するインストーラー・スクリプト・専用バージョンマネージャー
- 検証済みの公式リリース成果物
- 言語エコシステム標準のコマンド

POSIX では、ネイティブの symlink または実体を `$HOME/.local/bin` に配置する。Windows の単体バイナリも同じディレクトリに配置する。SDK や付随 payload を必要とする Windows ツールは、公式 distribution のディレクトリ構造を専用 root に保持し、その固定されたネイティブ実行ディレクトリを既存の User PATH 設定 script へ直接登録する。single-bin 統一のために独自の投影層を設けず、公式の Windows 手順に従って SDK 配布ディレクトリを PATH へ登録する。

導入は、既存の chezmoi run scripts と desired declarations の枠組みで表現する。独自 runtime proxy や wrapper、汎用 manager、PATH fragment ファイル、広い directory junction による投影、sandbox の権限拡大は採用しない。

ADR-002/003/013/021/022/027 が担う責務は、本 ADR の実施に伴って各責務を置換するときに個別に整理する。

## Consequences

ツールごとの導入経路が公式ドキュメントと一致し、mise の shim、lockfile、バージョン解決に起因する間接的な不整合が構造的に発生しなくなる。一方、ツール数だけ導入経路の実装と保守が個別化し、mise が担っていた単一コマンドでの一括更新と一覧の利便性は失われる。

POSIX と Windows の単体バイナリは共通の bin 配置を維持できるが、SDK 配布物を必要とする Windows ツールは専用 root と PATH 登録を必要とする。この差異を許容することで、独自の proxy、wrapper、junction 投影による複雑さと、実行時の探索規則を壊すリスクを避けられる。各責務は独立して置換でき、関連 ADR の Status は置換の時点で個別に整理する。
