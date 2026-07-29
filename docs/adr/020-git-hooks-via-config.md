# ADR-020: gitleaks の pre-commit は Git の設定ベースフックで配る

## Status

Accepted

## Context

[ADR-018](018-git-hooks-via-init-templatedir.md) は、共有ディレクトリの汚染を避けるため、機械全体への Git hook 配布を global の `core.hooksPath` から `init.templateDir` へ移した。この判断は維持する。

ただし、テンプレートは `git init` または `git clone` の時点でしかコピーされず、リポジトリ固有の hook マネージャはコピー後の `pre-commit` を置き換えられる。ADR-018 への移行時には既存リポジトリへの backfill が行われず、gitleaks が動いていない状態も通知されなかった。このため、作成時期に依存しない適用、repo-local hook との共存、無効状態の可視化が必要になった。

Git 2.54 の設定ベースフックは `$GIT_DIR/hooks` と別の層で加算的に実行されるが、それより前の Git は設定を警告なく無視する。検討した選択肢は次のとおりである。

- `init.templateDir` だけを使う案は ADR-018 の分離を保てるが、既存リポジトリと hook を置き換えたリポジトリを保護できない。
- global の `core.hooksPath` に戻す案は適用範囲を広げるが、ADR-018 が解消したリポジトリ間の汚染を再導入する。
- 設定ベースフックだけを使う案は Git 2.54 以降では要件を満たすが、古い Git の配布経路を失う。
- 設定ベースフックと `init.templateDir` を併用する案は二重実行への対処を要するが、両方の適用範囲を保てる。

## Decision

`dotfiles` は global gitconfig に `dotfiles-gitleaks` という設定ベースの `pre-commit` を登録する。global gitconfig を読み、かつこの hook を有効にした Git 2.54 以降は、リポジトリの作成時期と `$GIT_DIR/hooks` の内容にかかわらず gitleaks の起動スクリプトを実行する。

ADR-018 の `init.templateDir` は、Git 2.54 より前の配布経路として残す。テンプレート側の hook は、同じ Git が有効な `dotfiles-gitleaks` を列挙した場合だけ走査を省略する。判定できない場合はテンプレート側も実行し、未走査ではなく重複走査へ倒す。

`dotfiles` は macOS と Linux で Git 2.54 以降の導入と解決順を管理し、Windows では Git for Windows 2.54 以降を前提とする。利用者が選んだ Git を壊さないため、`/usr/local` の実体置換は Codespaces または Dev Container の既知の通常ファイルが古い Git を隠す場合に限り、既存の symlink と一般の Linux 環境には介入しない。

`chezmoi apply` は、実際に解決された Git の hook 一覧を確認する。設定ベースフックが無効なら原因別の警告を出すが、apply は失敗させず、出所を特定できない Git を自動変更しない。

構成と実装の対応は [`architecture.md`](../architecture.md#git-pre-commit-フック)、操作は [`operations.md`](../operations.md#git-pre-commit-フック)、復旧は [`troubleshooting.md`](../troubleshooting.md#設定ベースフックが全リポジトリで動いていない) を参照する。回帰条件は [`test_gitleaks_hook_sync.py`](../../tests/test_gitleaks_hook_sync.py) と [`test_git_shadow_resolution.py`](../../tests/test_git_shadow_resolution.py) が固定する。

## Consequences

- Git 2.54 以降の対象経路では、既存リポジトリと repo-local hook マネージャを使うリポジトリでも設定ベースフックが有効である限り gitleaks が起動する。repo-local hook 自体の実行は妨げない。
- Git 2.54 より前では ADR-018 の保証範囲だけが残るため、未 backfill の既存リポジトリと hook を置き換えたリポジトリは走査されない。
- 実行経路ごとに異なる Git が解決される環境では、保護の有無も経路ごとに異なり得る。macOS の PATH 調整は login shell を対象とし、shell 設定を読まない GUI アプリの経路までは保証しない。
- gitleaks の起動スクリプトが欠落または読み取り不能なら commit を拒否する。一方、スクリプトが gitleaks 本体を見つけられない場合は警告して commit を許可するため、この仕組みだけでは走査の実施を常に保証しない。欠落時の復旧は [`troubleshooting.md`](../troubleshooting.md#commit-が-gitleaks-pre-commit-not-found-で拒否される) を参照する。
- 設定ベース用とテンプレート用の起動スクリプトは、片方の撤去が他方を壊さないよう別ファイルに保つ。走査ロジックの重複は同期テストで管理する。
- `--no-verify` は両方の hook を回避できる。誤操作の早期検出を目的とし、意図的な持ち出しを防ぐ境界は GitHub 側の secret scanning と push protection が担う。
