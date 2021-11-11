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

apt-get -y install --no-install-recommends apt-transport-https ca-certificates curl gnupg2
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
add-apt-repository "deb [arch=$architecture] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
apt-get update
apt-get -y install docker-ce docker-ce-cli containerd.io
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