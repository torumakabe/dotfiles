#!/usr/bin/env bash

set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

if type cargo > /dev/null 2>&1; then
    rustup update
    cargo install-update --all
    exit 0
fi

curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

cargo install cargo-update
