#!/usr/bin/env bash
#
# Reffered to: https://github.com/microsoft/vscode-dev-containers/blob/main/script-library/github-debian.sh

set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install gh

# need interactive auth for intallation of extension
# gh extension install https://github.com/cappyzawa/gh-ghq-cd
# gh alias set cd ghq-cd
