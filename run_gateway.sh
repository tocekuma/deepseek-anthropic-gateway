#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${HOME}/Library/Application Support/Claude-3p/deepseek-gateway.env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 2
fi

set -a
source "${ENV_FILE}"
set +a

exec python3 "${SCRIPT_DIR}/server.py"
