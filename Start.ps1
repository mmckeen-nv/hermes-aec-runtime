$ErrorActionPreference = "Stop"
$Server = Join-Path $PSScriptRoot ".venv\Scripts\hermes-aec-mcp.exe"
if (-not (Test-Path $Server)) { throw "Not installed. Run .\Install.ps1 first." }
& $Server

