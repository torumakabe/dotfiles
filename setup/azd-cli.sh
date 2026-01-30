#!/usr/bin/env bash
set -eo pipefail

curl -fsSL https://aka.ms/install-azd.sh | bash -s -- -a "$(dpkg --print-architecture)"
