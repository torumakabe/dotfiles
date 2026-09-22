# ADR-019: クロスプラットフォーム機能等価性はプラットフォーム契約と静的検査で担保する

## Status

Accepted

## Context

過去に zsh 側の機能を修正・追加した際に PowerShell 対応が漏れ、4 環境（Windows/PowerShell、macOS/zsh、Linux/zsh、WSL/zsh）間で利用者体験が非対称になった事例があった。OS やツールの制約から実装を省略せざるを得ない場合もあるため、「実装の字面一致」ではなく「利用者目的の等価性」を基準とする。

Ubuntu runner では PowerShell を起動できるが、Windows 固有のパス解決、junction、WindowsApps alias は実行できない。これらは共有テストのスタブでは代替できず、Windows 実装の回帰が CI で常に skip されていた。一方、macOS 固有処理は CI へ追加する対象が限られ、runner を追加するセットアップ時間に見合う検査範囲がない。

## Decision

公開関数・alias・補完・ツール導入について、4 環境の対応状況を `PLATFORM_CONTRACT` として `tests/test_platform_parity.py` に記録する。変更時は全プラットフォームの実装を更新するか、理由と適用範囲を `exception: docs/...` 形式で契約と `docs/architecture.md` に記録する。

CI は `home/**` 変更で起動し（PR・main push 共通）、Ubuntu と Windows のジョブを並列実行する。Ubuntu ジョブは zsh を導入し、全単体テストと POSIX shell を使う hook smoke test を実行する。Windows ジョブは固定版の chezmoi と runner 標準の PowerShell を使い、全単体テストを実行する。git pre-commit フックや専用エージェント単独には依存せず、CI の機械検査、`.github/copilot-instructions.md` の規約、`review-repo` の意味判断を組み合わせる。

高リスク機能には両シェルで同じ期待結果を検証する共有の振る舞いテストを設け、実装差ではなく意味差を検出する。Windows 固有のパスと PowerShell 処理は Windows runner で検査する。macOS、WSL、利用者端末の構成に依存する実行時挙動は、各環境の実機スモークテストで確認する。

## Consequences

- **検出可能**：未分類の公開シンボル、実装アンカーの消失、共通ツールの install script 欠落、Windows 固有のパス処理と PowerShell 実装の回帰
- **検出不能**：macOS、WSL、利用者端末の設定や導入済みツールに依存する実行時の動作差。高リスク機能の意味差は共有振る舞いテストで補完する
- **Windows runner の限定採用**：Windows 固有テストだけを選別せず、Windows 上で全単体テストを実行する。テスト名の一覧を workflow に持たないことで追加時の登録漏れを防ぐ
- **完全な OS 行列は不採用**：macOS runner はセットアップ時間に対する検査範囲が小さいため追加しない。macOS と WSL に固有の動作は実機スモークテストで確認する
- **保守負担**：公開シンボルの追加・削除のたびに `PLATFORM_CONTRACT`・設定断片・例外文書を同期する必要がある
