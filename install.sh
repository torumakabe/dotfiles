#!/bin/sh
# Bootstrap script for chezmoi
# Used by GitHub Codespaces and first-time setup
# See: https://www.chezmoi.io/install/

set -eu

CHEZMOI_VERSION="2.70.0"

download_file() {
  url=$1
  output=$2

  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$output" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$output" "$url"
  else
    echo "error: curl or wget required to install chezmoi" >&2
    exit 1
  fi
}

sha256_file() {
  file=$1

  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  else
    echo "error: sha256sum or shasum required to verify chezmoi" >&2
    exit 1
  fi
}

mktemp_dir() {
  if tmp=$(mktemp -d 2>/dev/null); then
    echo "$tmp"
    return 0
  fi

  if tmp=$(mktemp -d -t chezmoi.XXXXXX 2>/dev/null); then
    echo "$tmp"
    return 0
  fi

  echo "error: unable to create temporary directory" >&2
  exit 1
}

if ! command -v chezmoi >/dev/null 2>&1; then
  bin_dir="$HOME/.local/bin"
  chezmoi="$bin_dir/chezmoi"

  case "$(uname -s)" in
    Linux) os="linux" ;;
    Darwin) os="darwin" ;;
    *)
      echo "error: unsupported OS: $(uname -s)" >&2
      exit 1
      ;;
  esac

  case "$(uname -m)" in
    x86_64 | amd64) arch="amd64" ;;
    aarch64 | arm64) arch="arm64" ;;
    *)
      echo "error: unsupported architecture: $(uname -m)" >&2
      exit 1
      ;;
  esac

  case "${os}-${arch}" in
    linux-amd64)
      archive="chezmoi_${CHEZMOI_VERSION}_linux_amd64.tar.gz"
      expected_sha256="32dbc87a4db7163d0f8c3156b631e3ee1cc6fed400f43ff467eca4211f2905e7"
      ;;
    linux-arm64)
      archive="chezmoi_${CHEZMOI_VERSION}_linux_arm64.tar.gz"
      expected_sha256="c65fb55bee4fb2bc14362998e2ce0cf1b1688bce0abfd7dd48cbac6448d6fc75"
      ;;
    darwin-amd64)
      archive="chezmoi_${CHEZMOI_VERSION}_darwin_amd64.tar.gz"
      expected_sha256="8d8abb5da0805ce6fa4d387cf3d9615281ad5b26007bf4d469af603ab3c237af"
      ;;
    darwin-arm64)
      archive="chezmoi_${CHEZMOI_VERSION}_darwin_arm64.tar.gz"
      expected_sha256="87142ac0465e9b1cd04a71c06c5164867fded7778c3c098f8efbea3ee9df1ade"
      ;;
    *)
      echo "error: unsupported platform: ${os}-${arch}" >&2
      exit 1
      ;;
  esac

  tmp_dir=$(mktemp_dir)
  trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM

  archive_path="${tmp_dir}/${archive}"
  archive_url="https://github.com/twpayne/chezmoi/releases/download/v${CHEZMOI_VERSION}/${archive}"

  echo "Downloading chezmoi ${CHEZMOI_VERSION}..."
  download_file "$archive_url" "$archive_path"

  actual_sha256=$(sha256_file "$archive_path")
  if [ "$actual_sha256" != "$expected_sha256" ]; then
    echo "error: checksum verification failed for $archive" >&2
    echo "expected: $expected_sha256" >&2
    echo "actual:   $actual_sha256" >&2
    exit 1
  fi

  mkdir -p "$bin_dir"
  tar -xzf "$archive_path" -C "$tmp_dir" chezmoi
  chmod 755 "${tmp_dir}/chezmoi"
  mv "${tmp_dir}/chezmoi" "$chezmoi"
else
  chezmoi=chezmoi
fi

exec "$chezmoi" init --apply torumakabe
