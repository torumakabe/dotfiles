#!/bin/bash

dir=~/dotfiles/files
olddir=~/dotfiles_old
files="bashrc bash_profile zshrc zprofile gitconfig"

mkdir -p $olddir
cd $dir

for file in $files; do
    if [ -f ~/.$file ]; then
      mv ~/.$file ~/dotfiles_old/
    fi
    ln -s $dir/$file ~/.$file
done

echo "Updating package lists..."
brew update

# Installing git & bash completion
echo ''
echo "Now installing git and bash-completion..."
brew install git && brew install bash-completion

# Setup other brew packages
echo "Now installing and configuring other brew packages..."
brew install azure-cli
brew install go
brew install python3
brew install n
brew install htop
brew install kubernetes-cli
brew install kubernetes-helm
brew install peco
brew install ghq
brew install zsh-completions
brew install jq
brew install fluxctl
brew install watch
brew install gh
brew install terraform

# temporarily disable for M1
<< 'MULTILINE-COMMENT'
brew tap azure/functions
brew install azure-functions-core-tools@3

brew install --cask google-chrome
brew install --cask docker
brew install --cask visual-studio-code
brew install --cask slack
brew install --cask postman
brew install --cask microsoft-azure-storage-explorer
brew install --cask dotnet-sdk
ln -s /usr/local/share/dotnet/dotnet /usr/local/bin/
MULTILINE-COMMENT

echo ''
echo 'Setup completed!'
