#!/usr/bin/env bash
# Copilot CLI hook launcher (Linux/macOS)
#
# Copilot CLI 1.0.90-6 以降、command hook は session sandbox 内で実行される。
# sandbox では mise が config、lockfile、state、downloads を読み書きできず、
# uv も project 検出や cache 初期化に追加の許可を必要とする。そのため hook は
# mise も uv も起動せず、chezmoi apply 時に記録した uv managed interpreter を
# 絶対パスで直接実行する。撤去条件は .github/copilot-instructions.md の
# ワークアラウンド一覧、撤去手順は docs/operations.md を参照する。
set -euo pipefail

fail() {
  echo "copilot hook launcher: $*" >&2
  exit 1
}

hooks_dir="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
runtime_file="${hooks_dir}/python-runtime.env"

[ "$#" -ge 1 ] || fail "usage: run-hook.sh <script-name> [args...]"
script_name="$1"
shift

case "${script_name}" in
*/* | *\\* | *..*) fail "script name must be a bare file name: ${script_name}" ;;
esac
script_path="${hooks_dir}/scripts/${script_name}"
[ -f "${script_path}" ] || fail "hook script not found: ${script_path}"

[ -r "${runtime_file}" ] || fail "missing ${runtime_file}; run chezmoi apply"

python_root=""
python_path=""
while IFS='=' read -r key value; do
  case "${key}" in
  python_root) python_root="${value}" ;;
  python) python_path="${value}" ;;
  esac
done <"${runtime_file}"

[ -n "${python_root}" ] || fail "${runtime_file} has no python_root; run chezmoi apply"
[ -n "${python_path}" ] || fail "${runtime_file} has no python; run chezmoi apply"
case "${python_root}" in
/*) ;;
*) fail "python_root must be absolute: ${python_root}" ;;
esac
case "${python_path}" in
"${python_root}"/*) ;;
*) fail "python must live under ${python_root}: ${python_path}" ;;
esac
[ -f "${python_path}" ] || fail "recorded interpreter is not a regular file: ${python_path}"
[ -x "${python_path}" ] || fail "recorded interpreter is not executable: ${python_path}"

exec "${python_path}" "${script_path}" "$@"
