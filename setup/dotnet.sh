#!/usr/bin/env bash

set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get update && apt-get install -y dotnet-sdk-8.0
