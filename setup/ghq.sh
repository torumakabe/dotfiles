#!/usr/bin/env bash
set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

go install github.com/x-motemen/ghq@latest
