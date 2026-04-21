# ADR-008: ~/.zshenv は ~/.profile を source する

## Status

Accepted

## Context

zsh は全起動モード（login / 非login / interactive / 非interactive）で `~/.zshenv` を読む。一方 `~/.zprofile` は login zsh でしか読まれない。

VS Code 統合ターミナルで `terminal.integrated.profiles.osx` の args を空で指定した場合や、一部の GUI アプリから spawn された zsh は **非 login** になる。そのケースでは `~/.zprofile` → `~/.profile` の連鎖が断ち切られ、brew / GOPATH / mise shims が PATH に入らない。実際に `~/.zshrc` 内の brew 参照（`az completion` など）が壊れていた。

## Decision

`~/.zshenv`（`home/dot_zshenv.tmpl`）で `~/.profile` を source する。`~/.profile` 側の `__DOTFILES_PROFILE_LOADED` ガードが二重実行を抑止するため、login zsh で `~/.zprofile` 経由でも読まれるケースや nested zsh でもコストは 1 回だけ。

## Consequences

- 非 login zsh でも共通 env が揃う（cold 約 30ms, warm 約 7ms）
- PATH 集約原則（ADR-001）が全 zsh モードで貫徹される
- `~/.zshenv` が重くなりすぎないよう、重い処理は入れない方針を維持する
