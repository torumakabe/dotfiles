#!/usr/bin/env bash
set -eo pipefail

echo "Installing draw.io from GitHub releases..."

ARCH=$(dpkg --print-architecture)
RELEASE_JSON=$(curl -fsSL https://api.github.com/repos/jgraph/drawio-desktop/releases/latest)

DEB_NAME=$(echo "$RELEASE_JSON" \
    | jq -r --arg arch "$ARCH" '.assets[] | select(.name | test("drawio-" + $arch + "-.*\\.deb$")) | .name')
LATEST_URL=$(echo "$RELEASE_JSON" \
    | jq -r --arg arch "$ARCH" '.assets[] | select(.name | test("drawio-" + $arch + "-.*\\.deb$")) | .browser_download_url')

if [ -z "$LATEST_URL" ] || [ -z "$DEB_NAME" ]; then
    echo "Failed to find draw.io .deb package for architecture: ${ARCH}"
    exit 1
fi

TMP_DEB=$(mktemp /tmp/drawio-XXXXXX.deb)
curl -fsSL -o "$TMP_DEB" "$LATEST_URL"

sudo dpkg -i "$TMP_DEB" || sudo apt-get -f -y install
rm -f "$TMP_DEB"
