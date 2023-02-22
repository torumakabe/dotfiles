#!/usr/bin/env bash
set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "Installing CUE..."
go install cuelang.org/go/cmd/cue@latest

echo "Installing FAST..."
go install github.com/ddo/fast@latest

echo "Installing ghq..."
go install github.com/x-motemen/ghq@latest

echo "Installing jump..."
go install github.com/gsamokovarov/jump@latest

echo "Installing kubelogin..."
go install github.com/Azure/kubelogin@latest

echo "Installing yq..."
go install github.com/mikefarah/yq/v4@latest
