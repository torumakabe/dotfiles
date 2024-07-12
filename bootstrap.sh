#!/usr/bin/env bash
# shellcheck disable=SC1090,SC1091
set -eo pipefail

dir=${HOME}/dotfiles/files
olddir=${HOME}/dotfiles_old
files="zshrc gitconfig gitconfig-linux gitconfig-mac gitconfig-windows gitconfig-corp cobra.yaml tigrc tmux.conf"

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

if [ "$1" = "link-only" ]
then
  echo ''
  echo "Setup completed! (Link only)"
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive

echo ''
echo "Now updating apt packages..."
sudo apt-get update

if [ "$1" = "setup-zsh" ]; then
  echo ''
  echo "Now setting up zsh..."
  sudo ./setup/zsh.sh

  echo ''
  echo "Now installing Oh My Zsh..."
  sudo ./setup/oh-my-zsh.sh

  echo ''
  echo "Change default shell to zsh..."
  sudo usermod --shell /bin/zsh "${USER}"
fi

echo ''
echo "Now setting up bash completion..."
sudo ./setup/bash-completion.sh

echo ''
echo "Now installing zsh completion..."
if [ ! -e "${HOME}/.oh-my-zsh/custom/plugins/zsh-completions" ]; then
  git clone https://github.com/zsh-users/zsh-completions "${HOME}/.oh-my-zsh/custom/plugins/zsh-completions"
fi

# Essential tools

echo ''
echo "Now installing apt packages..."
sudo apt-get -y install unzip
sudo apt-get -y install jq
sudo apt-get -y install software-properties-common
sudo apt-get -y install tig

echo ''
echo "Now installing vim..."
if ! type vim > /dev/null 2>&1; then
    sudo apt-get -y install vim
fi

echo ''
echo "Now installing git..."
if ! type git > /dev/null 2>&1; then
    sudo apt-get -y install git
fi

echo ''
echo "Now installing bat..."
if ! type batcat > /dev/null 2>&1; then
    sudo apt-get -y install bat
    mkdir -p "${HOME}/.local/bin"
    ln -s /usr/bin/batcat "${HOME}/.local/bin/bat"
fi

echo ''
echo "Now installing fzf..."
if ! type fzf > /dev/null 2>&1; then
    ./setup/fzf.sh
fi

echo ''
echo "Now installing GitHub CLI..."
if ! type gh > /dev/null 2>&1; then
    sudo ./setup/github-cli.sh
fi

echo ''
echo "Now installing .NET SDK..."
if ! type dotnet > /dev/null 2>&1; then
    sudo ./setup/dotnet.sh
fi

echo ''
echo "Now installing Node..."
if ! type node > /dev/null 2>&1; then
    sudo ./setup/node.sh
    export NVM_DIR=/usr/local/share/nvm
    [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
    [ -s "$NVM_DIR/bash_completion" ] && . "$NVM_DIR/bash_completion"
fi

echo ''
echo "Now checking Azure CLI completion file..."
if type az > /dev/null 2>&1; then
    if [ ! -f /etc/bash_completion.d/azure-cli ]; then
        curl -sLO 'https://raw.githubusercontent.com/Azure/azure-cli/dev/az.completion' && sudo mv az.completion /etc/bash_completion.d/azure-cli
    fi
fi

# If you are in Dev Container/GitHub Codespaces, the following steps are skipped because they could be installed by Dev Container templates or features

if [ "${REMOTE_CONTAINERS}" ] || [ "${CODESPACES}" ] > /dev/null 2>&1; then
    echo ''
    echo 'You are in a remote container. Skip the following steps.'
    echo "Setup completed!"
    exit 0
fi

echo ''
echo "Now installing 1Password CLI..."
if ! type op > /dev/null 2>&1; then
    ./setup/op.sh
fi

echo ''
echo "Now installing Azure CLI..."
if ! type az > /dev/null 2>&1; then
    sudo ./setup/az-cli.sh
fi

echo ''
echo "Now installing Azure Developer CLI..."
if ! type azd > /dev/null 2>&1; then
    sudo ./setup/azd-cli.sh
fi

echo ''
echo "Now installing Radius CLI..."
if ! type rad > /dev/null 2>&1; then
    ./setup/rad.sh
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
echo "Now installing Flux..."
if ! type flux > /dev/null 2>&1; then
    ./setup/flux.sh
fi

echo ''
echo "Now installing Trivy..."
if ! type trivy > /dev/null 2>&1; then
    ./setup/trivy.sh
fi

# Go, tools and apps that assume Go

echo ''
echo "Now installing Go..."
if ! type go > /dev/null 2>&1; then
    GOROOT=/usr/local/go
    GOPATH=$HOME/go
    sudo ./setup/go.sh "${GOROOT}" "${GOPATH}"
    export PATH=$PATH:${GOROOT}/bin
    export PATH=$PATH:${GOPATH}/bin
fi

echo ''
echo "Now installing go tools..."
./setup/go-tools.sh

echo ''
echo "Now installing go apps..."
./setup/go-apps.sh

echo ''
echo "Now installing Terraform..."
if ! type terraform > /dev/null 2>&1; then
    sudo env PATH="${PATH}" ./setup/terraform.sh
fi

# Rust, tools and apps that assume Rust

echo ''
echo "Now installing Rust..."
if ! type cargo > /dev/null 2>&1; then
    ./setup/rust.sh
    source "${HOME}/.cargo/env"
fi

echo ''
echo "Now installing Rust apps..."
./setup/rust-apps.sh

echo ''
echo 'Setup completed!'
