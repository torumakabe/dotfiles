{{- /*
Shared lightweight PATH bootstrap. POSIX-compatible.

Adds user-local tool directories to PATH if they exist and aren't already
present. Safe to source multiple times: the function dedupes, and missing
directories are silently skipped.

Ordering (last prepend wins the leftmost slot):
  1. ~/go/bin
  2. ~/.cargo/bin
  3. ~/.local/bin
  4. ~/.local/share/mise/shims  (mise-managed tools take precedence)

Callers are responsible for `export PATH` afterwards. The helper function is
defined and unset here, so it leaves no scope pollution behind.

Included from:
  - home/dot_profile.tmpl  (login shells, via ~/.profile)
  - home/dot_zshenv.tmpl   (every zsh invocation)
*/ -}}
__add_path() {
  case ":${PATH}:" in
    *":$1:"*) ;;
    *) [ -d "$1" ] && PATH="$1:${PATH}" ;;
  esac
}

__add_path "${HOME}/go/bin"
__add_path "${HOME}/.cargo/bin"
__add_path "${HOME}/.local/bin"
__add_path "${HOME}/.local/share/mise/shims"

unset -f __add_path
