#!/usr/bin/env bash
#
# Reffered to: https://github.com/microsoft/vscode-dev-containers/blob/main/script-library/kubectl-helm-debian.sh

set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

add-apt-repository -y ppa:longsleep/golang-backports
apt-get update
apt-get -y install golang-go
