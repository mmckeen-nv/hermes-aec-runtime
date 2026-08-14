[CmdletBinding()]
param([int]$RhinoPort = 10500, [switch]$AllowRhinoOffline)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Failures = [System.Collections.Generic.List[string]]::new()
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Server = Join-Path $Root ".venv\Scripts\hermes-aec-mcp.exe"
$Config = Join-Path $Root ".runtime\hermes-mcp.json"

if (-not (Test-Path -LiteralPath $Python)) { $Failures.Add("virtual environment missing; run Install.ps1") }
if (-not (Test-Path -LiteralPath $Server)) { $Failures.Add("MCP executable missing; run Install.ps1") }
if (-not (Test-Path -LiteralPath $Config)) { $Failures.Add("generated MCP configuration missing; run Install.ps1") }
if (Test-Path -LiteralPath $Python) {
    & $Python -c "import hermes_aec_runtime, mcp" 2>$null
    if ($LASTEXITCODE -ne 0) { $Failures.Add("Python package import failed") }
}

$RhinoOnline = $false
try {
    $Client = [System.Net.Sockets.TcpClient]::new()
    $Connect = $Client.ConnectAsync("127.0.0.1", $RhinoPort)
    if ($Connect.Wait(1000) -and $Client.Connected) { $RhinoOnline = $true }
    $Client.Dispose()
} catch { $RhinoOnline = $false }
if (-not $RhinoOnline -and -not $AllowRhinoOffline) { $Failures.Add("Rhino MCP is not listening on port $RhinoPort") }

if ($Failures.Count -gt 0) {
    $Failures | ForEach-Object { Write-Error "HERMES_AEC_DOCTOR_FAIL $_" }
    exit 1
}
Write-Host "HERMES_AEC_DOCTOR_OK config_version=1 rhino_online=$($RhinoOnline.ToString().ToLower())"
