#!/usr/bin/env bash
set -eo pipefail

dir=~/dotfiles/files
olddir=~/dotfiles_old
files="bash_profile zshrc gitconfig"

git clone https://github.com/ToruMakabe/dotfiles.git ~/dotfiles

mkdir -p $olddir
pushd $dir || exit

for file in $files; do
    if [ -f ~/."$file" ]; then
      mv ~/."$file" ~/dotfiles_old/
    fi
    ln -s $dir/"$file" ~/."$file"
done

popd

if [ "$1" = "link-only" ]
then
  echo ''
  echo "Setup completed! (Link only)"
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive

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
echo "Now installing Flux..."
if ! type flux > /dev/null 2>&1; then
    ./setup/flux.sh
fi

echo ''
echo "Now installing ghq..."
if ! type ghq > /dev/null 2>&1; then
    ./setup/ghq.sh
fi

echo ''
echo "Now installing jump..."
if ! type jump > /dev/null 2>&1; then
    ./setup/jump.sh
fi

echo ''
echo "Now installing Terraform..."
if ! type terraform > /dev/null 2>&1; then
    sudo ./setup/terraform.sh
fi

echo ''
echo 'Setup completed!'
