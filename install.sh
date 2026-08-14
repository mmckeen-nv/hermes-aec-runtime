#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11 or newer is required"'
[[ -x "$ROOT/.venv/bin/python" ]] || "$PYTHON" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -e "$ROOT[dev]"
mkdir -p "$ROOT/.runtime"
SERVER="$ROOT/.venv/bin/hermes-aec-mcp"
cat > "$ROOT/.runtime/hermes-mcp.json" <<EOF
{"schema_version":1,"mcpServers":{"hermes_aec":{"command":"$SERVER","args":[],"env":{"HERMES_AEC_CONFIG_VERSION":"1","HERMES_AEC_RHINO_URL":"${HERMES_AEC_RHINO_URL:-http://127.0.0.1:10500/}"}}}}
EOF
cat > "$ROOT/.runtime/install-manifest.json" <<EOF
{"schema_version":1,"root":"$ROOT","python":"$ROOT/.venv/bin/python"}
EOF
"$ROOT/doctor.sh" --allow-rhino-offline
echo "HERMES_AEC_INSTALLED config_version=1"
echo "Register .runtime/hermes-mcp.json with Hermes, then restart Hermes."
