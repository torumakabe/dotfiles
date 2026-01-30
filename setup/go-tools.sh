#!/usr/bin/env bash
set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "Installing fieldalignment..."
go install golang.org/x/tools/go/analysis/passes/fieldalignment/cmd/fieldalignment@latest
