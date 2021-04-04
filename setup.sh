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

if [ $# = 0 ]
then
  echo ''
  echo "Setup completed! (Link only)"
  exit 0
fi

if [ $1 != "install-tools" ]
then
  echo ''
  echo "Invalid parameter"
  exit 1
fi

echo "Updating package lists..."
sudo apt-get update

# Installing & config git

echo ''
echo "Now installing git..."
sudo apt-get install git -y


# Installing bash completion
echo ''
echo "Now installing bash-completion..."
sudo apt-get install git -y
sudo apt-get install bash-completion -y

# Installing zsh & zsh completion
echo ''
echo "Now installing zsh & zsh-completion..."
sudo apt-get install zsh -y
git clone https://github.com/zsh-users/zsh-completions ~/.zsh-completions
fpath=($HOME/.zsh-completions/src $fpath)
rm ~/.zcompdump
compinit -u

# Azure CLI Install
echo ''
echo "Now installing az cli..."
AZ_REPO=$(lsb_release -cs)
echo "deb [arch=amd64] https://packages.microsoft.com/repos/azure-cli/ $AZ_REPO main" | \
 sudo tee /etc/apt/sources.list.d/azure-cli.list
curl -L https://packages.microsoft.com/keys/microsoft.asc | sudo apt-key add -
sudo apt-get install apt-transport-https -y
sudo apt-get update && sudo apt-get install azure-cli -y

# kubectl Install
echo ''
echo "Now installing kubectl..."
sudo apt-get install -y apt-transport-https
curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
echo "deb https://apt.kubernetes.io/ kubernetes-xenial main" | sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update
sudo apt-get install -y kubectl

# Docker CE Install
echo ''
echo "Now installing Docker Client..."
sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common gnupg-agent
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io
sudo usermod -aG docker $USER

# Golang Install
echo ''
echo "Now installing golang..."
sudo add-apt-repository ppa:longsleep/golang-backports -y
sudo sudo apt-get install golang-go -y

# GitHub CLI Install
echo ''
echo "Now installing GitHub CLI..."
sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-key C99B11DEB97541F0
sudo apt-add-repository https://cli.github.com/packages
sudo apt update && sudo apt install gh -y

# Setup other packages
echo ''
echo "Now installing other apt packages..."
sudo apt-get install unzip -y
sudo apt-get install jq -y
sudo apt-get install python3 python3-venv -y
sudo apt-get install python3-pip -y
sudo apt-get install htop -y
sudo apt-get install peco -y

# node/n Install
echo ''
echo "Now installing node/nvm..."
sudo apt-get install -y nodejs npm
sudo npm cache clean
sudo npm install n -g
sudo n stable
sudo ln -sf /usr/local/bin/node /usr/bin/node
sudo apt-get purge -y nodejs

# Terraform Install
echo ''
echo "Now installing Terraform..."
curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo apt-key add -
sudo apt-add-repository "deb [arch=amd64] https://apt.releases.hashicorp.com $(lsb_release -cs) main"
sudo apt-get update && sudo apt-get install terraform -y

# helm Install
echo ''
echo "Now installing helm..."
curl https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3 | bash

# Change default editor to vim
echo ''
echo "Now changing default editor(to vim)..."
sudo update-alternatives --set editor /usr/bin/vim.basic


echo ''
echo 'Setup completed!'
