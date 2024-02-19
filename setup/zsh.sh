#!/usr/bin/env bash

set -eo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo -e 'Script must be run as root. Use sudo, su, or add "USER root" to your Dockerfile before running this script.'
    exit 1
fi

apt_get_update_if_needed()
{
    if [ ! -d "/var/lib/apt/lists" ] || [ "$(find /var/lib/apt/lists/ | wc -l)" = "0" ]; then
        echo "Running apt-get update..."
        apt-get update
    else
        echo "Skipping apt-get update."
    fi
}

export DEBIAN_FRONTEND=noninteractive

apt_get_update_if_needed
apt-get -y install zsh
