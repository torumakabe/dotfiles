# ADR-028: Copilot は mise 管理ツールを実体パスから実行する

## Status

Accepted

## Context

Copilot CLI のコマンドフックは通常、エージェントのシェルがログイン時に行う環境設定を共有せず、ランタイムの親プロセス環境を継承する。従来は `MISE_ENABLE_TOOLS=uv mise exec -- uv run ...` として、各フックの起動時に mise に実行対象を解決させていた。この方法は、フックごとに mise の起動と設定ファイルおよびロックファイルの読み込みを必要とし、親プロセスの `PATH` から mise 自体を実行できることを前提とする。mise によるツールの導入、バージョン固定、更新は引き続き必要である。

## Decision

mise は引き続きツールの導入、バージョン固定、更新を担う。Unix の共有プロファイルは公式の `mise env` でツールの実体を含む `PATH` を設定し、Windows は既存の `mise activate pwsh` を継承する。Copilot の5件のコマンドフック（`preToolUse` 3件、`postToolUse`、`postToolUseFailure`）は `mise exec` を経由せず、親プロセスの `PATH` から解決した `uv run` を直接起動する。通常の sandbox 内コマンドも継承した実体パスを使い、mise の設定ファイルやロックファイルを sandbox 内へ公開しない。

macOS のシムへのシンボリックリンク（ADR-002/003）と Windows のユーザー `PATH` へのシム登録は互換性のため維持するが、通常の Copilot 実行ではこれらを前提にしない。Dev Container と Codespaces では ADR-026 に従い sandbox の初回既定値を無効とする。本 ADR は、利用者が有効化した場合を含め、コンテナ内での sandbox 動作を保証しない。ツール管理には Linux と同じ mise 設定、ロックファイル、導入スクリプト、更新手順を使う。ローカル Dev Container だけは、コンテナ作成時の GitHub 未認証を避けるため、作成後に `mise install` を実行する（ADR-013）。

将来、`mxc` または Copilot の改善によって Windows sandbox が mise 設定を読めるようになっても、フックごとの mise 起動を避け、mise 設定やロックファイルを sandbox に公開せず、各環境で同じ実行方法を保てるため、実体パスからの直接実行には価値が残る。sandbox 内で mise の診断が必要になった場合、またはプロジェクト単位で動的にツールの版を切り替える必要が生じた場合に限り、mise またはシムを介した実行を再評価する。

## Consequences

- フックの起動ごとに mise を経由しないため、起動処理と親プロセスの `PATH` から mise を実行する必要がなくなる。
- Windows、macOS、WSL の通常の Copilot sandbox コマンドでは、mise 管理ツールが実体パスへ解決されることを観測した。
- macOS では、直接実行に変更した5件のコマンドフックを従来の `mise exec` 形式と比較実行し、終了コード、標準出力、標準エラー出力の一致を確認した。
- `tests/test_platform_parity.py` と `tests/test_copilot_hooks_config.py` の静的検査は、フックと設定のクロスプラットフォーム契約を検証する。
- Windows と WSL の直接実行フックのエンドツーエンド動作は、配布後の確認事項として残る。
- スタンドアロン Linux の sandbox とコンテナ内 sandbox については、動作確認済みとは主張しない。
- macOS のシムへのシンボリックリンクと Windows のユーザー `PATH` へのシム登録は残る。sandbox 内での mise 診断またはプロジェクト単位の動的な版切替が必要になるまで撤去を判断しない。
- ローカル Dev Container だけ導入タイミングが異なるため、運用者は初回に手動で GitHub 認証と `mise install` を行う必要がある（手順は ADR-013 と `docs/troubleshooting.md` を参照）。
