# ADR-018: 機械全体への Git hook 配布は init.templateDir で行う

## Status

Accepted

## Context

従来は `core.hooksPath = ~/.config/git/hooks` を GLOBAL に設定し、chezmoi で配布した `pre-commit`（gitleaks でステージ差分をスキャンし、repo-local な `.git/hooks/pre-commit` があれば `exec` で委譲）を全リポジトリに適用していた。狙いは gitleaks 未設定のリポジトリも含めた機械全体での保護。

この設計は事故を起こした。同一機械上の無関係なプロジェクトで素の `lefthook install` を実行したところ、lefthook は現在の `core.hooksPath` を尊重するため、生成した hook スタブ（`prepare-commit-msg` 等）が GLOBAL 設定のせいで共有ディレクトリ `~/.config/git/hooks/` に書き込まれた。これは dotfiles リポジトリ自身を含む全リポジトリを汚染し、無関係な commit で `Can't find lefthook in PATH` が出る原因になった。根本問題は、GLOBAL かつ共有かつ書き込み可能な `core.hooksPath` が、lefthook/husky/pre-commit のような「自リポジトリの hooks ディレクトリを専有する」前提の hook 管理ツールと構造的に相容れない点にある。

Python の `pre-commit` フレームワークには `pre-commit init-templatedir` という、まさに「機械全体へ hook を配布する」ための機能があり、`core.hooksPath` ではなく Git 純正の `init.templateDir` を使う。husky・lefthook も `core.hooksPath` の GLOBAL 設定を明示的に非推奨とし、自身の `install` は LOCAL に設定する。Git 自体の `.git/hooks/*.sample` もこのテンプレート機構で配布されており、奇策ではない。

## Decision

`core.hooksPath`（GLOBAL）を廃止し、`[init] templateDir = ~/.config/git/templates`（`home/dot_gitconfig.tmpl`）に切り替える。hook 本体は `home/dot_config/git/templates/hooks/executable_pre-commit` に移し（`~/.config/git/templates/hooks/pre-commit` へ配置）、repo-local hook への delegate/exec ロジックは削除する（テンプレート配布後は各リポジトリの通常の local hook になるため、委譲対象と自分自身が同一になり不要かつ自己ループの原因になる）。旧配置の `pre-commit` ファイルは `home/.chezmoiremove` で削除するが、旧ディレクトリ全体は削除しない。加えて、全 `ghq` リポジトリを走査して local `core.hooksPath` 上書き・hook 欠落・非 gitleaks hook・正常、を報告する読み取り専用の `git-hooks-audit`（zsh 関数 / PowerShell 関数）を追加する。

## Consequences

- `init.templateDir` は `git init`/`git clone` の瞬間に一度だけコピーされ、既存ファイルがあれば上書きしない（Git 本体の `copy_templates()` の挙動）。コピー後は完全に repo-local な通常ファイルになるため、他 hook マネージャの「バックアップ/上書き」判断も正しく働き、他リポジトリへの汚染は構造的に不可能になる。
- 保証が「常時・全リポジトリで強制」から「新規 init/clone 時にのみ自動配布」へ弱まる。既存リポジトリは `git -C <repo> init`（安全・冪等・既存ファイル非破壊）による一括バックフィルが必要。これは意図的に許容したトレードオフであり、機械全体での継続的強制と、他ツールから透過的な per-repo hook 管理は無調整では両立しないという Git の hook モデル上の制約による（設計時に内部レビュー2回で確認済み）。
- 他プロジェクトの hook マネージャが特定リポジトリの `.git/hooks/pre-commit` を上書きしても、影響はそのリポジトリ内に閉じる。
- テンプレートディレクトリは `hooks/pre-commit` のみを持ち、Git 既定の `*.sample` 等は引き継がない（この用途では無害・許容）。
- 「chezmoi apply のたびに旧共有ディレクトリの不明ファイルを自動削除する」案は、他プロジェクトの正規 hook を無警告で無効化しうる（hook ファイル欠落は git が黙って無視する）ため設計段階で明示的に却下した。可視性を保ちつつ自動破壊的操作を避けるため、読み取り専用の `git-hooks-audit` を採用した。
- Windows: hook 本体の POSIX `sh` 互換要件（Git for Windows が `/usr/bin/env bash` を WSL の bash.exe に解決し `C:/...` パスを開けない問題への対応）は変わらず適用される。
