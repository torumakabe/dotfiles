#!/usr/bin/env bash
#
# Reffered to: https://github.com/microsoft/vscode-dev-containers/blob/main/script-library/kubectl-helm-debian.sh

set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-key adv --keyserver keyserver.ubuntu.com --recv-key C99B11DEB97541F0
apt-add-repository https://cli.github.com/packages
apt update
apt install -y gh

gh extension install https://github.com/cappyzawa/gh-ghq-cd
gh alias set cd ghq-cd
