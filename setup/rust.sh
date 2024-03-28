#!/usr/bin/env bash
# shellcheck disable=SC1090,SC1091
set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

if type cargo > /dev/null 2>&1; then
    rustup update
    cargo install-update --all
    exit 0
fi

sudo apt install libssl-dev

curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "${HOME}/.cargo/env"

cargo install cargo-update
