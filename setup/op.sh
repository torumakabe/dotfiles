#!/usr/bin/env bash
set -eo pipefail

OP_VERSION="2.14.0"

architecture="$(uname -m)"
case ${architecture} in
    x86_64) architecture="amd64";;
    aarch64 | armv8*) architecture="arm64";;
    aarch32 | armv7* | armvhf*) architecture="arm";;
    i?86) architecture="386";;
    *) echo "(!) Architecture ${architecture} unsupported"; exit 1 ;;
esac

wget https://cache.agilebits.com/dist/1P/op2/pkg/v"${OP_VERSION}"/op_linux_"${architecture}"_v"${OP_VERSION}".zip
unzip -u op_linux_"${architecture}"_v"${OP_VERSION}".zip

mkdir -p "${HOME}"/.gnupg
echo "keyserver keyserver.ubuntu.com" >> "${HOME}"/.gnupg/gpg.conf
gpg --receive-keys 3FEF9748469ADBE15DA7CA80AC2D62742012EA22
gpg --verify op.sig op

sudo mv op /usr/local/bin/op

rm ./op.sig
rm ./op_linux_"${architecture}"_v"${OP_VERSION}".zip
