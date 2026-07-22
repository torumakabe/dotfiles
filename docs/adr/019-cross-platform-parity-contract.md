# ADR-019: クロスプラットフォーム機能等価性はプラットフォーム契約と静的検査で担保する

## Status

Accepted

## Context

過去に zsh 側の機能を修正・追加した際に PowerShell 対応が漏れ、4 環境（Windows/PowerShell、macOS/zsh、Linux/zsh、WSL/zsh）間で利用者体験が非対称になった事例があった。OS/ツール制約から実装を省略せざるを得ない場合もあるため、「実装の字面一致」ではなく「利用者目的の等価性」を基準とする。また GitHub Actions の OS 行列（Windows/macOS/Ubuntu ランナー）を追加するとセットアップコストが高く、OS 固有の実機動作は CI 行列で代替できない。

## Decision

公開関数・alias・補完・ツール導入について、4 環境の対応状況を `PLATFORM_CONTRACT` として `tests/test_platform_parity.py` に記録する。変更時は全プラットフォームの実装を更新するか、理由と適用範囲を `exception: docs/...` 形式で契約と `docs/architecture.md` に記録する。

理由付き例外（現状）：`e` / `mise-self-upgrade` は winget 管理の Windows 固有機能（ADR-011）；`completion:terraform` は公式 PowerShell completion が存在しない；`completion:rad` は Windows 向け公式配布を確認できない。

CI は `home/**` 変更で起動し（PR・main push 共通）、`command -v zsh` / `command -v pwsh` を確認してから `uv run -m unittest discover -s tests -v` を実行する（`test_ci_installs_and_requires_both_shells_before_unittest` で検証済み）。git pre-commit フックや専用エージェント単独には依存せず、CI 機械検査・`.github/copilot-instructions.md` の規約・`review-repo` の意味判断を組み合わせる。

高リスク機能には両シェルで同じ期待結果を検証する共有の振る舞いテストを設け、実装差ではなく意味差を検出する。CI で保証できない OS 固有の実行時挙動は、4 環境の実機スモークテストで確認する。

## Consequences

- **検出可能**：未分類の公開シンボル、実装アンカーの消失、共通ツールの install script 欠落
- **検出不能**：各 OS 実行時の実際の動作差（パス解決・出力形式等）。高リスク機能の意味差は共有振る舞いテストで補完する
- **OS 行列不採用**：ubuntu-latest で両シェルの存在を確認し、OS 固有動作は 4 環境の実機スモークテストで補う。Windows/macOS/Ubuntu Actions 行列は認証・環境セットアップコストに対してカバレッジ増分が小さいため採用しない
- **保守負担**：公開シンボルの追加・削除のたびに `PLATFORM_CONTRACT`・設定断片・例外文書を同期する必要がある
