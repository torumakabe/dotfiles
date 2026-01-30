#!/usr/bin/env bash
# shellcheck disable=SC1090,SC1091
set -eo pipefail

dir=${HOME}/dotfiles/files
olddir=${HOME}/dotfiles_old
files="zshrc gitconfig gitconfig-linux gitconfig-mac gitconfig-windows gitconfig-corp"

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

# Link .mise.toml to home for global tool access
if [ ! -e "${HOME}/.mise.toml" ]; then
    ln -s "${HOME}/dotfiles/.mise.toml" "${HOME}/.mise.toml"
fi

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
sudo apt-get -y install unzip jq software-properties-common keychain

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
echo "Now installing mise..."
if ! type mise > /dev/null 2>&1; then
    ./setup/mise.sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo ''
echo "Now installing tools via mise..."
mise install

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

# Go tools and apps

echo ''
echo "Now installing go tools..."
./setup/go-tools.sh

echo ''
echo "Now installing go apps..."
./setup/go-apps.sh

# Rust (for tools that require cargo)

echo ''
echo "Now installing Rust..."
if ! type cargo > /dev/null 2>&1; then
    ./setup/rust.sh
    source "${HOME}/.cargo/env"
fi

# AI tools

echo ''
echo "Now installing GitHub Copilot CLI..."
if ! type copilot > /dev/null 2>&1; then
    ./setup/copilot-cli.sh
fi

echo ''
echo 'Setup completed!'
