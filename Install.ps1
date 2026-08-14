[CmdletBinding()]
param(
    [switch]$SkipHermesRegistration,
    [ValidateRange(1024, 65535)][int]$RhinoPort = 1999,
    [ValidateRange(1024, 65535)][int]$LegacyRhinoPort = 10500,
    [switch]$DisableLegacyFallback,
    [switch]$EnableLegacyFallback,
    [switch]$SkipRhinoMCPInstall,
    [string]$RhinoMCPVersion = "0.4.0-aec.2"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Runtime = Join-Path $Root ".runtime"
$Python = Get-Command python -ErrorAction Stop

if (-not $SkipRhinoMCPInstall) {
    & (Join-Path $Root "Install-RhinoMCP.ps1") -Version $RhinoMCPVersion
}

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
    schema_version = 2
    mcpServers = @{
        hermes_aec = @{
            command = $Server
            args = @()
            env = @{
                HERMES_AEC_CONFIG_VERSION = "2"
                HERMES_AEC_RHINOMCP_HOST = "127.0.0.1"
                HERMES_AEC_RHINOMCP_PORT = "$RhinoPort"
                HERMES_AEC_LEGACY_RHINO_URL = "http://127.0.0.1:$LegacyRhinoPort/"
                HERMES_AEC_ENABLE_LEGACY_FALLBACK = $(if ($EnableLegacyFallback -and -not $DisableLegacyFallback) { "1" } else { "0" })
            }
        }
    }
}
$Config | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $Runtime "hermes-mcp.json") -Encoding utf8
@{
    schema_version = 2
    installed_at = (Get-Date).ToUniversalTime().ToString("o")
    root = $Root
    python = $VenvPython
} | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $Runtime "install-manifest.json") -Encoding utf8

if (-not $SkipHermesRegistration) {
    & (Join-Path $Root "Register-Hermes.ps1") -RhinoPort $RhinoPort -LegacyRhinoPort $LegacyRhinoPort -DisableLegacyFallback:$DisableLegacyFallback -EnableLegacyFallback:$EnableLegacyFallback
}
& (Join-Path $Root "Doctor.ps1") -RhinoPort $RhinoPort -AllowRhinoOffline
Write-Host "HERMES_AEC_INSTALLED config_version=2 rhinomcp_port=$RhinoPort legacy_fallback=$(($EnableLegacyFallback -and -not $DisableLegacyFallback).ToString().ToLower())"
Write-Host "Restart Hermes and Rhino. In Rhino run AECMCPStart, then use a demo shortcut."
