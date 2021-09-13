# Configure WSL

## Setup Windows by Boxstarter

```
Set-ExecutionPolicy RemoteSigned
. { iwr -useb http://boxstarter.org/bootstrapper.ps1 } | iex; get-boxstarter -Force
Install-BoxstarterPackage -PackageName "https://raw.githubusercontent.com/ToruMakabe/dotfiles/wsl/boxstarter.txt"  -DisableReboots
```

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
