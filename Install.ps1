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

function Test-CompatiblePython([string]$Candidate) {
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate)) { return $false }
    $VersionText = & $Candidate -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>$null
    return ($LASTEXITCODE -eq 0 -and $VersionText -and [version]$VersionText -ge [version]"3.11")
}

# Hermes Desktop already ships a real Python runtime. Prefer it over PATH, where Windows' optional
# Microsoft Store app-execution alias can masquerade as python.exe but cannot execute anything.
$HermesPython = Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\venv\Scripts\python.exe"
$PythonSource = if (Test-CompatiblePython $HermesPython) { $HermesPython } else { $null }
if (-not $PythonSource) {
    $PathPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($PathPython -and (Test-CompatiblePython $PathPython.Source)) { $PythonSource = $PathPython.Source }
}
if (-not $PythonSource) {
    $HermesUv = Join-Path $env:LOCALAPPDATA "hermes\bin\uv.exe"
    $UvCommand = Get-Command uv.exe -ErrorAction SilentlyContinue
    $Uv = if (Test-Path -LiteralPath $HermesUv) { $HermesUv } elseif ($UvCommand) { $UvCommand.Source } else { $null }
    if (-not $Uv) { throw "Hermes' managed Python and uv runtimes are missing. Repair Hermes Desktop, then rerun deployment." }
    Write-Host "Installing an isolated Python 3.12 runtime with Hermes uv."
    & $Uv python install 3.12
    if ($LASTEXITCODE) { throw "Hermes uv could not install Python 3.12." }
    $PythonSource = (& $Uv python find 3.12).Trim()
    if ($LASTEXITCODE -or -not (Test-CompatiblePython $PythonSource)) { throw "Hermes uv installed Python but it could not be validated." }
}

if (-not $SkipRhinoMCPInstall) {
    & (Join-Path $Root "Install-RhinoMCP.ps1") -Version $RhinoMCPVersion
}

if (-not (Test-Path -LiteralPath (Join-Path $Root ".venv\Scripts\python.exe"))) {
    & $PythonSource -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE) { throw "Could not create the Hermes AEC runtime environment with $PythonSource." }
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
