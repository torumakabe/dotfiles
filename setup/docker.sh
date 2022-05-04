#!/usr/bin/env bash

set -eo pipefail

apt_get_update_if_needed()
{
    if [ ! -d "/var/lib/apt/lists" ] || [ "$(ls /var/lib/apt/lists/ | wc -l)" = "0" ]; then
        echo "Running apt-get update..."
        apt-get update
    else
        echo "Skipping apt-get update."
    fi
}

export DEBIAN_FRONTEND=noninteractive

apt_get_update_if_needed

architecture="$(uname -m)"
case $architecture in
    x86_64) architecture="amd64";;
    aarch64 | armv8*) architecture="arm64";;
    aarch32 | armv7* | armvhf*) architecture="arm";;
    i?86) architecture="386";;
    *) echo "(!) Architecture $architecture unsupported"; exit 1 ;;
esac

apt-get -y install --no-install-recommends ca-certificates curl gnupg lsb-release
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update
apt-get -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin
usermod -aG docker "${SUDO_USER}"

# dockerd without docker desktop
#
# groupmod -g 36257 docker
# DOCKER_DIR=/mnt/wsl/shared-docker
# mkdir -p "$DOCKER_DIR"
# chmod o=,g=rx "$DOCKER_DIR"
# chgrp docker "$DOCKER_DIR"
# mkdir /etc/docker/
# tee /etc/docker/daemon.json << EOT
# {
#   "hosts": ["unix:///mnt/wsl/shared-docker/docker.sock"]
# }
# EOT
