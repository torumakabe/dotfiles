#!/usr/bin/env bash

set -eo pipefail

COMPOSE_VERSION="v2.3.3"

export DEBIAN_FRONTEND=noninteractive

architecture="$(uname -m)"

# Install docker compose v2
DOCKER_CONFIG=${DOCKER_CONFIG:-$HOME/.docker}
mkdir -p "${DOCKER_CONFIG}/cli-plugins"
curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${architecture}" -o "${DOCKER_CONFIG}/cli-plugins/docker-compose"
chmod +x "${DOCKER_CONFIG}/cli-plugins/docker-compose"
