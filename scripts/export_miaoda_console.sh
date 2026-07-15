#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$ROOT_DIR/miaoda-console"
TARGET_DIR="${1:-$ROOT_DIR/../aixhs666-console}"

if [[ ! -f "$SOURCE_DIR/.spark/meta.json" ]]; then
  echo "Miaoda source not found at $SOURCE_DIR" >&2
  exit 1
fi

if [[ ! -d "$TARGET_DIR/.git" || ! -f "$TARGET_DIR/.spark/meta.json" ]]; then
  echo "Miaoda release checkout not found at $TARGET_DIR" >&2
  exit 1
fi

rsync -a --delete \
  --exclude='.git/' \
  --exclude='node_modules/' \
  --exclude='dist/' \
  --exclude='.env.local' \
  --exclude='logs/' \
  "$SOURCE_DIR/" "$TARGET_DIR/"

echo "Miaoda source exported to $TARGET_DIR"
echo "Review, test, commit, and push sprint/default from the release checkout."

