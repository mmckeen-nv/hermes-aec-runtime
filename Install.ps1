$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Python = Get-Command python -ErrorAction Stop
& $Python.Source -m venv (Join-Path $Root ".venv")
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e "$Root[dev]"
New-Item -ItemType Directory -Force (Join-Path $Root ".runtime") | Out-Null
$Server = Join-Path $Root ".venv\Scripts\hermes-aec-mcp.exe"
@{ mcpServers = @{ hermes_aec = @{ command = $Server; args = @() } } } |
  ConvertTo-Json -Depth 5 | Set-Content (Join-Path $Root ".runtime\hermes-mcp.json")
Write-Host "Installed. Run .\Start.ps1 or copy .runtime\hermes-mcp.json into your Hermes MCP configuration."
Write-Host "For the deployed AEC profiles, run .\Register-Hermes.ps1 and restart Hermes."
