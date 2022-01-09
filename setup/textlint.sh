#!/usr/bin/env bash

set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

if ! type npm > /dev/null 2>&1; then
    echo 'npm is not installed. Please try again after installation.'
    exit 1
fi

npm install -g textlint textlint-filter-rule-allowlist textlint-rule-preset-ja-technical-writing textlint-rule-preset-jtf-style
