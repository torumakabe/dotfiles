#!/usr/bin/env bash

set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

curl -s https://fluxcd.io/install.sh | sudo bash
sudo chmod +x /usr/local/bin/flux
