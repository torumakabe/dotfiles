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
brew install oven-sh/bun/bun

dir=${HOME}/dotfiles/files
olddir=${HOME}/dotfiles_old
files="zshrc gitconfig gitconfig-mac gitconfig-corp cobra.yaml tigrc tmux.conf"

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

echo ''
echo 'Setup completed!'

# Install Oh My Zsh and plugins separetely
# Oh My Zsh: https://ohmyz.sh/#install
# zsh_completion plugin: https://github.com/zsh-users/zsh-completions
