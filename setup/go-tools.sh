#!/usr/bin/env bash
set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "Installing golangci-lint..."
# binary will be $(go env GOPATH)/bin/golangci-lint
curl -sSfL https://raw.githubusercontent.com/golangci/golangci-lint/master/install.sh | sh -s -- -b $(go env GOPATH)/bin

golangci-lint version

echo "Installing fieldalignment..."
go install golang.org/x/tools/go/analysis/passes/fieldalignment/cmd/fieldalignment@latest
