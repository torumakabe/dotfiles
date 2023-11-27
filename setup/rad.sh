#!/usr/bin/env bash
set -eo pipefail

wget -q "https://raw.githubusercontent.com/radius-project/radius/main/deploy/install.sh" -O - | /bin/bash
