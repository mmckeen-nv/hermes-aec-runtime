#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" != "--keep-environment" ]]; then
  rm -rf -- "$ROOT/.venv" "$ROOT/.runtime"
fi
echo "HERMES_AEC_UNINSTALLED"
