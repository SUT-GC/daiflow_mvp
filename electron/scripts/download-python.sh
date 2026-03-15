#!/bin/bash
set -e

# 下载 python-build-standalone 的独立 Python 构建
# https://github.com/indygreg/python-build-standalone

PYTHON_VERSION="3.11"
PBS_VERSION="20241016"
DOWNLOAD_DIR="$(dirname "$0")/../python-runtime"

mkdir -p "$DOWNLOAD_DIR"

echo "Downloading Python standalone builds..."

# macOS Apple Silicon (arm64)
if [ ! -d "$DOWNLOAD_DIR/darwin-arm64" ]; then
  echo "Downloading Python for macOS arm64..."
  curl -L "https://github.com/indygreg/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PYTHON_VERSION}.10+${PBS_VERSION}-aarch64-apple-darwin-install_only.tar.gz" \
    -o "/tmp/python-darwin-arm64.tar.gz"
  mkdir -p "$DOWNLOAD_DIR/darwin-arm64"
  tar -xzf "/tmp/python-darwin-arm64.tar.gz" -C "$DOWNLOAD_DIR/darwin-arm64" --strip-components=1
  rm "/tmp/python-darwin-arm64.tar.gz"
  echo "✓ macOS arm64 Python downloaded"
fi

# macOS Intel (x64)
if [ ! -d "$DOWNLOAD_DIR/darwin-x64" ]; then
  echo "Downloading Python for macOS x64..."
  curl -L "https://github.com/indygreg/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PYTHON_VERSION}.10+${PBS_VERSION}-x86_64-apple-darwin-install_only.tar.gz" \
    -o "/tmp/python-darwin-x64.tar.gz"
  mkdir -p "$DOWNLOAD_DIR/darwin-x64"
  tar -xzf "/tmp/python-darwin-x64.tar.gz" -C "$DOWNLOAD_DIR/darwin-x64" --strip-components=1
  rm "/tmp/python-darwin-x64.tar.gz"
  echo "✓ macOS x64 Python downloaded"
fi

echo ""
echo "Python runtime ready:"
ls -lh "$DOWNLOAD_DIR"
