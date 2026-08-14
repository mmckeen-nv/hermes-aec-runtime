[CmdletBinding()]
param(
    [switch]$SkipHermesRegistration,
    [int]$RhinoPort = 10500
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Runtime = Join-Path $Root ".runtime"
$Python = Get-Command python -ErrorAction Stop

if ([version](& $Python.Source -c "import sys; print('.'.join(map(str, sys.version_info[:3])))") -lt [version]"3.11") {
    throw "Python 3.11 or newer is required."
}

if (-not (Test-Path -LiteralPath (Join-Path $Root ".venv\Scripts\python.exe"))) {
    & $Python.Source -m venv (Join-Path $Root ".venv")
}
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e "$Root[dev]"

New-Item -ItemType Directory -Force $Runtime | Out-Null
$Server = (Join-Path $Root ".venv\Scripts\hermes-aec-mcp.exe").Replace("\", "/")
$Config = @{
    schema_version = 1
    mcpServers = @{
        hermes_aec = @{
            command = $Server
            args = @()
            env = @{
                HERMES_AEC_CONFIG_VERSION = "1"
                HERMES_AEC_RHINO_URL = "http://127.0.0.1:$RhinoPort/"
            }
        }
    }
}
$Config | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $Runtime "hermes-mcp.json") -Encoding utf8
@{
    schema_version = 1
    installed_at = (Get-Date).ToUniversalTime().ToString("o")
    root = $Root
    python = $VenvPython
} | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $Runtime "install-manifest.json") -Encoding utf8

if (-not $SkipHermesRegistration) {
    & (Join-Path $Root "Register-Hermes.ps1") -RhinoPort $RhinoPort
}
& (Join-Path $Root "Doctor.ps1") -RhinoPort $RhinoPort -AllowRhinoOffline
Write-Host "HERMES_AEC_INSTALLED config_version=1"
Write-Host "Restart Hermes, open Rhino, then ask Hermes to inspect or modify the active model."
