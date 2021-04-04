#!/bin/bash

dir=~/dotfiles/files
olddir=~/dotfiles_old
files="bash_profile zshrc gitconfig"

mkdir -p $olddir
cd $dir

for file in $files; do
    if [ -f ~/.$file ]; then
      mv ~/.$file ~/dotfiles_old/
    fi
    ln -s $dir/$file ~/.$file
done

echo ''
echo 'Setup completed!'
