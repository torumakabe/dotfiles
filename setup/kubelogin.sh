#!/usr/bin/env bash
set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

go install github.com/Azure/kubelogin@latest
