#!/usr/bin/env bash

set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
