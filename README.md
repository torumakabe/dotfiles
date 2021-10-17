# Configure WSL

## Prerequisite & TODO

* [Install WSL](https://docs.microsoft.com/ja-jp/windows/wsl/install)
* Override /etc/wsl.conf
* Override Windows Terminal settings
* Install Windows apps

## Setup (in WSL)

```
git clone https://github.com/ToruMakabe/dotfiles.git ~/dotfiles
cd ~/dotfiles
git switch wsl
./bootstrap.sh install-tools
```

## Setup (Link only)

```
git clone https://github.com/ToruMakabe/dotfiles.git ~/dotfiles
cd ~/dotfiles
git switch wsl
./bootstrap.sh
```
