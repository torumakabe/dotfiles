#!/usr/bin/env bash

set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

sudo apt-get update && sudo apt-get install -y dotnet-sdk-8.0
