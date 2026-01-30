#!/usr/bin/env bash
set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "Installing FAST..."
go install github.com/ddo/fast@latest

echo "Installing jump..."
go install github.com/gsamokovarov/jump@latest
