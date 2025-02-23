#!/usr/bin/env bash
set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "Installing ripgrep..."
cargo install ripgrep
cargo install cargo-make
