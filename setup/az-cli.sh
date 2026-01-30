#!/usr/bin/env bash
set -eo pipefail

MICROSOFT_GPG_KEYS_URI="https://packages.microsoft.com/keys/microsoft.asc"

if [ "$(id -u)" -ne 0 ]; then
    echo -e 'Script must be run as root. Use sudo, su, or add "USER root" to your Dockerfile before running this script.'
    exit 1
fi

architecture="$(uname -m)"
case $architecture in
    x86_64) architecture="amd64";;
    aarch64 | armv8*) architecture="arm64";;
    aarch32 | armv7* | armvhf*) architecture="arm";;
    i?86) architecture="386";;
    *) echo "(!) Architecture $architecture unsupported"; exit 1 ;;
esac

# Get central common setting
get_common_setting() {
    if [ "${common_settings_file_loaded}" != "true" ]; then
        curl -sfL "https://aka.ms/vscode-dev-containers/script-library/settings.env" 2>/dev/null -o /tmp/vsdc-settings.env || echo "Could not download settings file. Skipping."
        common_settings_file_loaded=true
    fi
    if [ -f "/tmp/vsdc-settings.env" ]; then
        local multi_line=""
        if [ "$2" = "true" ]; then multi_line="-z"; fi
        local result
        result="$(grep ${multi_line} -oP "$1=\"?\K[^\"]+" /tmp/vsdc-settings.env | tr -d '\0')"
        if [ -n "${result}" ]; then declare -g "$1"="${result}"; fi
    fi
    echo "$1=${!1}"
}

# Function to run apt-get if needed
apt_get_update_if_needed()
{
    if [ ! -d "/var/lib/apt/lists" ] || [ "$(find /var/lib/apt/lists/ | wc -l)" = "0" ]; then
        echo "Running apt-get update..."
        apt-get update
    else
        echo "Skipping apt-get update."
    fi
}

# Checks if packages are installed and installs them if not
check_packages() {
    if ! dpkg -s "$@" > /dev/null 2>&1; then
        apt_get_update_if_needed
        apt-get -y install --no-install-recommends "$@"
    fi
}

export DEBIAN_FRONTEND=noninteractive

# Install dependencies
if [ "${architecture}" = "arm64" ] || [ "${architecture}" = "arm" ]; then
    check_packages \
        apt-transport-https \
        ca-certificates \
        gcc \
        python3-dev \
        python3-pip \
        build-essential \
        curl \
        libffi-dev
else
    check_packages \
        apt-transport-https \
        ca-certificates \
        curl \
        gnupg2 \
        lsb-release
fi

# Workaround for ARM (https://github.com/Azure/azure-cli/issues/5657)
if [ "${architecture}" = "arm64" ] || [ "${architecture}" = "arm" ]; then
    pip install --upgrade pip setuptools wheel
    pip install azure-cli
    curl -sLO 'https://raw.githubusercontent.com/Azure/azure-cli/dev/az.completion' && mv az.completion /etc/bash_completion.d/azure-cli
    exit 0
fi

# Import key safely (new 'signed-by' method rather than deprecated apt-key approach) and install
. /etc/os-release
get_common_setting MICROSOFT_GPG_KEYS_URI
curl -sSL ${MICROSOFT_GPG_KEYS_URI} | gpg --dearmor > /usr/share/keyrings/microsoft-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/microsoft-archive-keyring.gpg] https://packages.microsoft.com/repos/azure-cli/ ${VERSION_CODENAME} main" > /etc/apt/sources.list.d/azure-cli.list
apt-get update
apt-get install -y azure-cli
