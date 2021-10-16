#!/usr/bin/env bash
set -eo pipefail

dir=~/dotfiles/files
olddir=~/dotfiles_old
files="bash_profile zshrc gitconfig"

mkdir -p $olddir
pushd "$dir" || exit

for file in $files; do
    if [ -f ~/."$file" ]; then
      mv ~/."$file" ~/dotfiles_old/
    fi
    ln -s $dir/"$file" ~/."$file"
done

popd

if [ $# = 0 ]
then
  echo ''
  echo "Setup completed! (Link only)"
  exit 0
fi

if [ "$1" != "install-tools" ]
then
  echo ''
  echo "Invalid parameter"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

echo ''
echo "Now setting up bash..."
sudo ./setup/bash-common.sh

echo ''
echo "Now setting up zsh..."
sudo ./setup/zsh-common.sh

echo ''
echo "Now installing Oh My Zsh..."
./setup/oh-my-zsh.sh
if [ ! -e "${HOME}/.oh-my-zsh/custom/plugins/zsh-completions" ]; then
  git clone https://github.com/zsh-users/zsh-completions "${HOME}/.oh-my-zsh/custom/plugins/zsh-completions"
fi

echo ''
echo "Now installing apt packages..."
sudo apt-get update
sudo apt-get -y install unzip
sudo apt-get -y install jq
sudo apt-get -y install python3 python3-venv
sudo apt-get -y install python3-pip

echo ''
echo "Now installing jump..."
if ! type jump > /dev/null 2>&1; then
    ./setup/jump.sh
fi

echo ''
echo "Now installing 1Password CLI..."
if ! type op > /dev/null 2>&1; then
    ./setup/op.sh
fi

echo ''
echo "Now installing fzf..."
if ! type fzf > /dev/null 2>&1; then
    ./setup/fzf.sh
fi

echo ''
echo "Now installing Azure CLI..."
if ! type az > /dev/null 2>&1; then
    sudo ./setup/az-cli.sh
fi

echo ''
echo "Now installing docker..."
if ! type docker > /dev/null 2>&1; then
    sudo ./setup/docker.sh
fi

echo ''
echo "Now installing kubectl & helm..."
if ! type kubectl > /dev/null 2>&1; then
    sudo ./setup/kubectl-helm.sh
fi

echo ''
echo "Now installing Go..."
if ! type go > /dev/null 2>&1; then
    sudo ./setup/go.sh
fi

echo ''
echo "Now installing GitHub CLI..."
if ! type gh > /dev/null 2>&1; then
    sudo ./setup/github-cli.sh
fi

echo ''
echo "Now installing Terraform..."
if ! type terraform > /dev/null 2>&1; then
    sudo ./setup/terraform.sh
fi

echo ''
echo 'Setup completed!'
