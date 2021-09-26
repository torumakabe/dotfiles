#!/usr/bin/env bash
set -eo pipefail

export DEBIAN_FRONTEND=noninteractive

fzf_install_dir="${HOME}/.fzf"
if [ ! -d "${fzf_install_dir}" ]; then
    git clone --depth 1 https://github.com/junegunn/fzf.git "${fzf_install_dir}"
    "${fzf_install_dir}/install" --all
else
    pushd "${fzf_install_dir}"
    git pull
    "${fzf_install_dir}/install" --all
    popd
fi
