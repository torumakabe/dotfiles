#!/bin/sh
# Bootstrap script for chezmoi
# Used by GitHub Codespaces and first-time setup
# See: https://www.chezmoi.io/install/

set -e

if ! command -v chezmoi >/dev/null 2>&1; then
  bin_dir="$HOME/.local/bin"
  chezmoi="$bin_dir/chezmoi"
  if command -v curl >/dev/null 2>&1; then
    sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$bin_dir"
  elif command -v wget >/dev/null 2>&1; then
    sh -c "$(wget -qO- get.chezmoi.io)" -- -b "$bin_dir"
  else
    echo "error: curl or wget required to install chezmoi" >&2
    exit 1
  fi
else
  chezmoi=chezmoi
fi

exec "$chezmoi" init --apply torumakabe
