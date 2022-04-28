#!/usr/bin/env bash
set -eo pipefail

dir=${HOME}/dotfiles/files
olddir=${HOME}/dotfiles_old
files="zshrc gitconfig cobra.yaml"

if [ ! -e "${HOME}/dotfiles" ]; then
    git clone https://github.com/ToruMakabe/dotfiles.git ${HOME}/dotfiles
fi

mkdir -p $olddir
pushd $dir || exit

for file in $files; do
    if [ -f ${HOME}/."$file" ]; then
      mv ${HOME}/."$file" ${HOME}/dotfiles_old/
    fi
    ln -s $dir/"$file" ${HOME}/."$file"
done

popd

if [ "$1" = "link-only" ]
then
  echo ''
  echo "Setup completed! (Link only)"
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive

if [ "$1" = "setup-shell" ]
then
  echo ''
  echo "Now setting up bash..."
  sudo ./setup/bash-common.sh

  echo ''
  echo "Now setting up zsh..."
  sudo ./setup/zsh-common.sh
fi

echo ''
echo "Now installing Oh My Zsh..."
./setup/oh-my-zsh.sh
if [ ! -e "${HOME}/.oh-my-zsh/custom/plugins/zsh-completions" ]; then
  git clone https://github.com/zsh-users/zsh-completions "${HOME}/.oh-my-zsh/custom/plugins/zsh-completions"
fi

echo ''
echo "Change default shell to zsh..."
sudo usermod --shell /bin/zsh ${USER}

echo ''
echo "Now installing apt packages..."
sudo apt-get update
sudo apt-get -y install unzip
sudo apt-get -y install jq
sudo apt-get -y install libssl-dev

echo ''
echo "Now updating git..."
sudo ./setup/git.sh

echo ''
echo "Now installing bat..."
if ! type batcat > /dev/null 2>&1; then
    sudo apt-get -y install bat
    mkdir -p ${HOME}/.local/bin
    ln -s /usr/bin/batcat ${HOME}/.local/bin/bat
fi

echo ''
echo "Now installing 1Password CLI..."
if ! type op > /dev/null 2>&1; then
    ./setup/op.sh
fi

echo ''
echo "Now installing Go..."
if ! type go > /dev/null 2>&1; then
    sudo ./setup/go.sh
    export GOROOT=/usr/local/go
    export PATH=$PATH:$GOROOT/bin
    export GOPATH=$HOME/go
    export PATH=$PATH:$GOPATH/bin
fi

echo ''
echo "Now installing fzf..."
if ! type fzf > /dev/null 2>&1; then
    ./setup/fzf.sh
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
    ./setup/krew.sh
fi

echo ''
echo "Now installing kubelogin..."
if ! type kubelogin > /dev/null 2>&1; then
    ./setup/kubelogin.sh
fi

echo ''
echo "Now installing Flux..."
if ! type flux > /dev/null 2>&1; then
    ./setup/flux.sh
fi

echo ''
echo "Now installing GitHub CLI..."
if ! type gh > /dev/null 2>&1; then
    ./setup/github-cli.sh
fi

echo ''
echo "Now installing Rust..."
if ! type cargo > /dev/null 2>&1; then
    ./setup/rust.sh
fi

echo ''
echo "Now installing rg..."
if ! type rg > /dev/null 2>&1; then
    cargo install ripgrep
fi

echo ''
echo 'Setup completed!'
