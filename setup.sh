#!/bin/bash

dir=~/dotfiles/files
olddir=~/dotfiles_old
files="bashrc bash_profile zshrc gitconfig"

mkdir -p $olddir
cd $dir

for file in $files; do
    mv ~/.$file ~/dotfiles_old/
    ln -s $dir/$file ~/.$file
done

echo ''
echo 'Setup completed!'
