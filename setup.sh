#!/bin/bash

dir=~/dotfiles/files
olddir=~/dotfiles_old
files="bash_profile zshrc gitconfig"

git clone https://github.com/ToruMakabe/dotfiles.git ~/dotfiles

mkdir -p $olddir
cd $dir || exit

for file in $files; do
    if [ -f ~/."$file" ]; then
      mv ~/."$file" ~/dotfiles_old/
    fi
    ln -s $dir/"$file" ~/."$file"
done

echo ''
echo "Now installing jump..."
wget https://github.com/gsamokovarov/jump/releases/download/v0.40.0/jump_0.40.0_amd64.deb && sudo dpkg -i jump_0.40.0_amd64.deb

echo ''
echo 'Setup completed!'
