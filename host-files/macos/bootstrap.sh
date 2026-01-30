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
brew install python@3
brew install ghq
brew install jump
brew install 1password-cli
brew install azure-cli
brew tap azure/azd && brew install azd
brew install --cask devtoys
brew install --cask dotnet-sdk
brew tap microsoft/dev-proxy
brew install dev-proxy
brew install --cask codex
brew install copilot-cli
brew install mise

# Rust (rustup - official installer)
echo "Now installing Rust..."
if ! type cargo > /dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
fi

dir=${HOME}/dotfiles/files
olddir=${HOME}/dotfiles_old
files="zshrc gitconfig gitconfig-mac gitconfig-corp"

if [ ! -e "${HOME}/dotfiles" ]; then
    git clone https://github.com/torumakabe/dotfiles.git "${HOME}/dotfiles"
fi

mkdir -p "$olddir"
pushd "$dir" || exit

for file in $files; do
    if [ -f "${HOME}/.$file" ]; then
      mv "${HOME}/.$file" "${HOME}/dotfiles_old/"
    fi
    ln -s "$dir/$file" "${HOME}/.$file"
done

popd

# Link .mise.toml to home for global tool access
if [ ! -e "${HOME}/.mise.toml" ]; then
    ln -s "${HOME}/dotfiles/.mise.toml" "${HOME}/.mise.toml"
fi

echo ''
echo "Now installing tools via mise..."
mise install

echo ''
echo 'Setup completed!'

# Install Oh My Zsh and plugins separately
# Oh My Zsh: https://ohmyz.sh/#install
# zsh_completion plugin: https://github.com/zsh-users/zsh-completions
