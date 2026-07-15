#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

exec "$ROOT_DIR/.venv/bin/uvicorn" \
  apps.operator_gateway:create_operator_gateway \
  --factory \
  --host 127.0.0.1 \
  --port "${OPERATOR_GATEWAY_PORT:-8020}"
