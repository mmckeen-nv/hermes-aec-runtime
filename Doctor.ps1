[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)][int]$RhinoPort = 1999,
    [switch]$AllowRhinoOffline,
    [string[]]$Profile = @("cliff-house-modifications-windows", "cliff-house-full-build-windows"),
    [switch]$SkipProfileCheck
)

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
if (Test-Path -LiteralPath $Config) {
    try {
        $Generated = Get-Content -Raw -LiteralPath $Config | ConvertFrom-Json
        if ($Generated.schema_version -ne 2 -or -not $Generated.mcpServers.hermes_aec.command) {
            $Failures.Add("generated MCP configuration is invalid")
        } elseif (-not (Test-Path -LiteralPath $Generated.mcpServers.hermes_aec.command)) {
            $Failures.Add("generated MCP configuration points to a missing executable")
        }
    } catch { $Failures.Add("generated MCP configuration is not valid JSON") }
}
if (-not $SkipProfileCheck) {
    foreach ($Name in $Profile) {
        $ProfileConfig = Join-Path $env:LOCALAPPDATA "hermes\profiles\$Name\config.yaml"
        if (-not (Test-Path -LiteralPath $ProfileConfig)) { continue }
        $ProfileText = Get-Content -Raw -LiteralPath $ProfileConfig
        if ($ProfileText -notmatch '(?m)^  # BEGIN HERMES AEC SIDECAR \(managed\)$' -or
            $ProfileText -notmatch [regex]::Escape($Server.Replace('\', '/'))) {
            $Failures.Add("Hermes profile is not registered to this runtime: $Name")
        }
    }
}

$RhinoOnline = $false
$RhinoOwner = $null
try {
    $Listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $RhinoPort -State Listen -ErrorAction Stop | Select-Object -First 1
    $RhinoOwner = Get-Process -Id $Listener.OwningProcess -ErrorAction Stop
    if ($RhinoOwner.ProcessName -eq "Rhino") { $RhinoOnline = $true }
    else { $Failures.Add("port $RhinoPort is owned by $($RhinoOwner.ProcessName), not Rhino") }
} catch { $RhinoOnline = $false }
if (-not $RhinoOnline -and -not $AllowRhinoOffline) { $Failures.Add("Rhino MCP is not listening on port $RhinoPort") }

$PluginManifest = Get-ChildItem -LiteralPath (Join-Path $env:APPDATA "McNeel\Rhinoceros\packages\8.0\rhinomcp") -Filter manifest.yml -File -Recurse -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $PluginManifest) { $Failures.Add("RhinoMCP plugin is not installed; run Install-RhinoMCP.ps1") }

if ($Failures.Count -gt 0) {
    $Failures | ForEach-Object { Write-Error "HERMES_AEC_DOCTOR_FAIL $_" }
    exit 1
}
$PluginVersion = if ($PluginManifest) { Split-Path -Leaf (Split-Path -Parent $PluginManifest.FullName) } else { "missing" }
$OwnerPid = if ($RhinoOwner) { $RhinoOwner.Id } else { 0 }
Write-Host "HERMES_AEC_DOCTOR_OK config_version=2 rhino_online=$($RhinoOnline.ToString().ToLower()) rhino_pid=$OwnerPid rhinomcp_version=$PluginVersion"
