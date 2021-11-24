#!/usr/bin/env bash
set -eo pipefail

OP_VERSION="1.12.3"

wget https://cache.agilebits.com/dist/1P/op/pkg/v"${OP_VERSION}"/op_linux_amd64_v"${OP_VERSION}".zip
unzip -u op_linux_amd64_v"${OP_VERSION}".zip

mkdir -p "${HOME}"/.gnupg
echo "keyserver keyserver.ubuntu.com" >> "${HOME}"/.gnupg/gpg.conf
gpg --receive-keys 3FEF9748469ADBE15DA7CA80AC2D62742012EA22
gpg --verify op.sig op

sudo mv op /usr/local/bin/op

rm ./op.sig
rm ./op_linux_amd64_v"${OP_VERSION}".zip
