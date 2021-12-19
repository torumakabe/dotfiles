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

add-apt-repository -y ppa:git-core/ppa
apt_get_update_if_needed
apt-get -y install git
