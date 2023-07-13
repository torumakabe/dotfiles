#!/usr/bin/env bash
#
# Reffered to: https://github.com/microsoft/vscode-dev-containers/blob/main/script-library/azcli-debian.sh

set -eo pipefail

curl -fsSL https://aka.ms/install-azd.sh | bash -s -- -a "$(dpkg --print-architecture)"
