#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALLOW_OFFLINE=false
[[ "${1:-}" == "--allow-rhino-offline" ]] && ALLOW_OFFLINE=true
[[ -x "$ROOT/.venv/bin/python" ]] || { echo "HERMES_AEC_DOCTOR_FAIL virtual environment missing" >&2; exit 1; }
[[ -x "$ROOT/.venv/bin/hermes-aec-mcp" ]] || { echo "HERMES_AEC_DOCTOR_FAIL MCP executable missing" >&2; exit 1; }
[[ -f "$ROOT/.runtime/hermes-mcp.json" ]] || { echo "HERMES_AEC_DOCTOR_FAIL generated config missing" >&2; exit 1; }
"$ROOT/.venv/bin/python" -c 'import hermes_aec_runtime, mcp'
RHINO_ONLINE=false
if "$ROOT/.venv/bin/python" -c 'import socket; s=socket.create_connection(("127.0.0.1",10500),1); s.close()' 2>/dev/null; then RHINO_ONLINE=true; fi
if [[ "$RHINO_ONLINE" == false && "$ALLOW_OFFLINE" == false ]]; then
  echo "HERMES_AEC_DOCTOR_FAIL Rhino MCP is not listening on port 10500" >&2
  exit 1
fi
echo "HERMES_AEC_DOCTOR_OK config_version=1 rhino_online=$RHINO_ONLINE"
