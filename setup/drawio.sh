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

if ! sudo dpkg -i "$TMP_DEB"; then
    echo "dpkg failed, attempting to fix dependencies..."
    sudo apt-get -f -y install
fi
rm -f "$TMP_DEB"

if ! type drawio > /dev/null 2>&1; then
    echo "draw.io installation failed"
    exit 1
fi
