#!/usr/bin/env bash
# Build Tailwind CSS using the standalone CLI (no Node required).
# Downloads the binary on first run, picking the right arch for the host.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$ROOT_DIR/scripts/bin"
BIN="$BIN_DIR/tailwindcss"
INPUT="$ROOT_DIR/app/static/src/input.css"
OUTPUT="$ROOT_DIR/app/static/dist/app.css"
VERSION="v3.4.17"

ensure_binary() {
  if [[ -x "$BIN" ]]; then
    return 0
  fi

  local arch os asset
  arch="$(uname -m)"
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"

  case "$os-$arch" in
    linux-x86_64)  asset="tailwindcss-linux-x64" ;;
    linux-aarch64) asset="tailwindcss-linux-arm64" ;;
    linux-armv7l)  asset="tailwindcss-linux-armv7" ;;
    darwin-x86_64) asset="tailwindcss-macos-x64" ;;
    darwin-arm64)  asset="tailwindcss-macos-arm64" ;;
    *)
      echo "Unsupported platform: $os-$arch" >&2
      exit 1
      ;;
  esac

  mkdir -p "$BIN_DIR"
  local url="https://github.com/tailwindlabs/tailwindcss/releases/download/$VERSION/$asset"
  echo "Downloading Tailwind standalone CLI ($asset @ $VERSION)..."
  curl -sSL -o "$BIN" "$url"
  chmod +x "$BIN"
}

ensure_binary

cd "$ROOT_DIR"

if [[ "${1:-}" == "--watch" ]]; then
  exec "$BIN" -i "$INPUT" -o "$OUTPUT" --watch
else
  "$BIN" -i "$INPUT" -o "$OUTPUT" --minify
fi
