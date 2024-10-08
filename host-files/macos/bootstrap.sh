#!/usr/bin/env bash
set -eo pipefail

echo "Updating package lists..."
brew update

# Setup other brew packages
echo "Now installing and configuring other brew packages..."
brew install zsh-completions
brew install watch
brew install jq
brew install gh
brew install go
brew install node
brew install python@3
brew install ghq
brew install jump
brew install fzf
brew install 1password-cli
brew install azure-cli
brew tap azure/azd && brew install azd
brew install kubernetes-cli
brew install kubernetes-helm
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
brew install --cask devtoys
brew install --cask dotnet-sdk
brew tap microsoft/dev-proxy
brew install dev-proxy

echo ''
echo 'Setup completed!'

# Install Oh My Zsh separetely
# https://ohmyz.sh/#install
