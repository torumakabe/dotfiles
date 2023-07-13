#!/usr/bin/env bash
set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

LATEST_VERSION=$(curl -s https://api.github.com/repos/sigstore/cosign/releases/latest | grep tag_name | cut -d : -f2 | tr -d "v\", ")
curl -s -O -L "https://github.com/sigstore/cosign/releases/latest/download/cosign_${LATEST_VERSION}_amd64.deb"
dpkg -i "cosign_${LATEST_VERSION}_amd64.deb"
rm "cosign_${LATEST_VERSION}_amd64.deb"
