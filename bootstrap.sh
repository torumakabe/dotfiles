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

echo ''
echo "Now installing jump..."
if ! type jump > /dev/null 2>&1; then
    ./setup/jump.sh
fi

echo ''
echo "Now installing Azure CLI..."
if ! type az > /dev/null 2>&1; then
    sudo ./setup/az-cli.sh
fi

echo ''
echo "Now installing docker..."
if ! type docker > /dev/null 2>&1; then
    sudo ./setup/docker-in-docker.sh
fi

echo ''
echo "Now installing kubectl & helm..."
if ! type kubectl > /dev/null 2>&1; then
    sudo ./setup/kubectl-helm.sh
fi

echo ''
echo 'Setup completed!'
