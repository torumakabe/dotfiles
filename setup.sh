#!/bin/bash

dir=~/dotfiles/files
olddir=~/dotfiles_old
files="bashrc bash_profile zshrc gitconfig"

mkdir -p $olddir
cd $dir

# Install brew
/usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"

echo "Updating package lists..."
brew update

# Installing git & bash completion
echo ''
echo "Now installing git and bash-completion..."
brew install git && brew install bash-completion

# Setup other brew packages
echo "Now installing and configuring other brew packages..."
brew install hugo
brew install azure-cli
brew install go
brew install python3
brew install n
brew install tmux
brew install htop
brew install reattach-to-user-namespace
brew install kubernetes-cli
brew install kubernetes-helm
brew install graphviz
brew install direnv
brew install peco
brew install ghq
brew install hub
brew install zsh
brew install zsh-completions
brew install jq
brew install fluxctl
brew install gpg
brew install pinentry-mac
brew install watch

brew install github/gh/gh

brew install hashicorp/tap/terraform

brew tap azure/functions
brew install azure-functions-core-tools

brew tap homebrew/cask-cask

brew cask install google-chrome
brew cask install docker
brew cask install visual-studio-code
brew cask install slack
brew cask install postman
brew cask install microsoft-azure-storage-explorer
brew cask install dotnet-sdk
ln -s /usr/local/share/dotnet/dotnet /usr/local/bin/

echo ''
echo 'Setup completed!'
