#!/bin/sh
# Bootstrap script for chezmoi
# Used by GitHub Codespaces and first-time setup
# See: https://www.chezmoi.io/install/

set -eu

CHEZMOI_VERSION="2.74.1"

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
      expected_sha256="ae01c66b1a6dbf563667c63fbbd9986b3cfa3c98dd266ddee732f63e8af2e9d1"
      ;;
    linux-arm64)
      archive="chezmoi_${CHEZMOI_VERSION}_linux_arm64.tar.gz"
      expected_sha256="8c62619c4303770342e7c7e75d168b6cc6efee4ad5e4b994980de7cf794d68e2"
      ;;
    darwin-arm64)
      archive="chezmoi_${CHEZMOI_VERSION}_darwin_arm64.tar.gz"
      expected_sha256="fbc7b86c7b36eb0448e2a99a616b6d32f022d1f3895076ad44f4c5d65a77fe60"
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

if [ "${CHEZMOI_INSTALL_ONLY:-}" = "1" ]; then
  # dotfiles を適用せずにバイナリだけを導入する。CI がこの経路で
  # テスト用の chezmoi を入れる。
  exit 0
fi

exec "$chezmoi" init --apply torumakabe
