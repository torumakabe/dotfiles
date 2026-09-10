# ADR-028: Copilot は mise 管理ツールを実体パスから実行する

## Status

Accepted

## Context

Copilot CLI のコマンドフックは通常、エージェントのシェルがログイン時に行う環境設定を共有せず、ランタイムの親プロセス環境を継承する。従来は `MISE_ENABLE_TOOLS=uv mise exec -- uv run ...` として、各フックの起動時に mise に実行対象を解決させていた。この方法は、フックごとに mise の起動と設定ファイルおよびロックファイルの読み込みを必要とし、親プロセスの `PATH` から mise 自体を実行できることを前提とする。mise によるツールの導入、バージョン固定、更新は引き続き必要である。

以前コミットした候補を読み込んだ新規 WSL タブでは `~/.profile` が正常に読み込まれ、`__DOTFILES_MISE_PATH` は mise の install path 30 件、shim 0 件を含んだ。しかし、その後の対話 zsh 起動で `mise activate zsh` が mise shims を `PATH` の先頭へ置いた。この状態から新規起動した Copilot CLI では、検証対象の mise 管理コマンド 43 件すべてが shim 経由で解決され、install path は `PATH` の後方に残った。`MISE_SHELL` と `__MISE_DIFF` も設定されており、zsh activation の環境が親プロセスから継承されたことを確認した。

## Decision

mise は引き続きツールの導入、バージョン固定、更新を担う。Unix では対話 zsh の `mise activate zsh` を削除し、対話・非対話 shell とも共有 profile の公式 `mise env` が設定する実体 `PATH` を使う。Windows は既存の `mise activate pwsh` を維持する。Copilot の5件のコマンドフック（`preToolUse` 3件、`postToolUse`、`postToolUseFailure`）は `mise exec` を経由せず、親プロセスの `PATH` から解決した `uv run` を直接起動する。通常の sandbox 内コマンドも継承した実体パスを使い、mise の設定ファイルやロックファイルを sandbox 内へ公開しない。

macOS のシムへのシンボリックリンク（ADR-002/003）と Windows のユーザー `PATH` へのシム登録は互換性のため維持するが、通常の Copilot 実行ではこれらを前提にしない。Dev Container と Codespaces では ADR-026 に従い sandbox の初回既定値を無効とする。本 ADR は、利用者が有効化した場合を含め、コンテナ内での sandbox 動作を保証しない。ツール管理には Linux と同じ mise 設定、ロックファイル、導入スクリプト、更新手順を使う。ローカル Dev Container だけは、コンテナ作成時の GitHub 未認証を避けるため、作成後に `mise install` を実行する（ADR-013）。

wrapper、継続的な `PATH` 修復、custom updater は追加しない。Unix ではディレクトリ移動時の自動バージョン切替を保証せず、それが必須要件になった場合に限り activation、mise または shim を介した実行を再評価する。

## Consequences

- フックの起動ごとに mise を経由しないため、起動処理と親プロセスの `PATH` から mise を実行する必要がなくなる。
- macOS と Windows の通常の Copilot sandbox コマンドでは、mise 管理ツールが実体パスへ解決されることを観測した。
- WSL では共有 profile 単独の `PATH` に install path 30 件、shim 0 件を確認した一方、zsh activation を継承した Copilot CLI では検証対象 43 件すべてが shim 経由になった。これは全コマンド一般ではなく、当該検証集合に対する観測である。
- macOS では、直接実行に変更した5件のコマンドフックを従来の `mise exec` 形式と比較実行し、終了コード、標準出力、標準エラー出力の一致を確認した。
- `tests/test_platform_parity.py` と `tests/test_copilot_hooks_config.py` の静的検査は、Unix で zsh activation を使わないことを含む、フックと設定のクロスプラットフォーム契約を検証する。Windows と、zsh activation 削除後の WSL における直接実行フックのエンドツーエンド動作は、配布後の確認事項として残る。
- スタンドアロン Linux の sandbox とコンテナ内 sandbox については、動作確認済みとは主張しない。
- macOS のシムへのシンボリックリンクと Windows のユーザー `PATH` へのシム登録は残るが、Unix の通常実行は shim を前提にしない。
- ローカル Dev Container だけ導入タイミングが異なるため、運用者は初回に手動で GitHub 認証と `mise install` を行う必要がある（手順は ADR-013 と `docs/troubleshooting.md` を参照）。
