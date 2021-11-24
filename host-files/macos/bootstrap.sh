#!/usr/bin/env bash
set -eo pipefail

echo "Updating package lists..."
brew update

# Installing bash completion
echo ''
echo "Now installing bash-completion..."
brew install bash-completion
mkdir -p ~/.zsh/completions
curl https://raw.githubusercontent.com/Azure/azure-cli/dev/az.completion -o ~/.zsh/completions/az.completion

# Installing Oh My Zsh
echo ''
echo "Now installing Oh My Zsh..."
../../setup/oh-my-zsh.sh

# Setup other brew packages
echo "Now installing and configuring other brew packages..."
brew install zsh-completions
brew install watch
brew install jq
brew install gh
brew install go
brew install ghq
brew install jump
brew install fzf
# brew install kubernetes-cli
# brew install kubernetes-helm

echo ''
echo 'Setup completed!'
