#!/usr/bin/env bash
set -eo pipefail

echo "Installing draw.io from GitHub releases..."

ARCH=$(dpkg --print-architecture)
RELEASE_JSON=$(curl -fsSL https://api.github.com/repos/jgraph/drawio-desktop/releases/latest)

DEB_NAME=$(echo "$RELEASE_JSON" \
    | jq -r ".assets[] | select(.name | test(\"drawio-${ARCH}-.*\\.deb$\")) | .name")
LATEST_URL=$(echo "$RELEASE_JSON" \
    | jq -r ".assets[] | select(.name | test(\"drawio-${ARCH}-.*\\.deb$\")) | .browser_download_url")

if [ -z "$LATEST_URL" ] || [ -z "$DEB_NAME" ]; then
    echo "Failed to find draw.io .deb package for architecture: ${ARCH}"
    exit 1
fi

EXPECTED_SHA256=$(echo "$RELEASE_JSON" \
    | jq -r ".body" \
    | grep -F "$DEB_NAME" \
    | grep -oP 'sha256:\K[0-9a-f]{64}')

if [ -z "$EXPECTED_SHA256" ]; then
    echo "Failed to find SHA256 checksum for ${DEB_NAME}"
    exit 1
fi

TMP_DEB=$(mktemp /tmp/drawio-XXXXXX.deb)
curl -fsSL -o "$TMP_DEB" "$LATEST_URL"

ACTUAL_SHA256=$(sha256sum "$TMP_DEB" | awk '{print $1}')
if [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
    echo "Checksum mismatch! Expected: ${EXPECTED_SHA256}, Got: ${ACTUAL_SHA256}"
    rm -f "$TMP_DEB"
    exit 1
fi

sudo apt-get -y install "$TMP_DEB"
rm -f "$TMP_DEB"
