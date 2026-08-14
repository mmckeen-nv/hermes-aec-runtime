#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -e "$ROOT[dev]"
mkdir -p "$ROOT/.runtime"
printf '{"mcpServers":{"hermes_aec":{"command":"%s/.venv/bin/hermes-aec-mcp","args":[]}}}\n' "$ROOT" > "$ROOT/.runtime/hermes-mcp.json"
echo "Installed. Run ./start.sh or copy .runtime/hermes-mcp.json into Hermes."

