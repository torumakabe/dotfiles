# ADR-001: PATH 管理を ~/.profile に集約する

## Status

Accepted

## Context

macOS と Linux で使うシェルは zsh / bash / sh に加え、VS Code 統合ターミナルや IDE エージェント、`bash -c` で起動するスクリプトなど非対話・非 login のシェルも多い。PATH 設定を個別 rc ファイルに重複して書くと、ケースごとに欠落（brew / GOPATH / mise shims が見えない等）が発生する。

## Decision

PATH を含む共通 env の唯一の情報源を `~/.profile`（`home/dot_profile.tmpl`）に置き、各シェルの起動ファイルからそれを source する。再入を防ぐため `__DOTFILES_PROFILE_LOADED` ガードを用いる。

- `~/.bash_profile` → `~/.profile`
- `~/.zprofile` → `~/.profile`
- `~/.zshenv` → `~/.profile`（ADR-008 参照）
- `sh` / `dash` は `~/.profile` を直接読む

## Consequences

- どのシェル経路でも PATH が揃う。非 login zsh からの brew / mise shims 参照が壊れない
- PATH 変更は `~/.profile` の一箇所で完結する
- ガードにより同一プロセスツリーでの再実行コストはゼロ。cold でも約 30ms
- Windows は PowerShell プロファイル側で別管理（この ADR の対象外）
