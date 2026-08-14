[CmdletBinding()]
param(
    [string[]]$Profile = @("cliff-house-modifications-windows", "cliff-house-full-build-windows"),
    [int]$RhinoPort = 10500
)

$ErrorActionPreference = "Stop"
$Server = Join-Path $PSScriptRoot ".venv\Scripts\hermes-aec-mcp.exe"
if (-not (Test-Path -LiteralPath $Server)) { throw "Run Install.ps1 first." }
$ServerYaml = $Server.Replace("\", "/")
$Begin = "  # BEGIN HERMES AEC SIDECAR (managed)"
$End = "  # END HERMES AEC SIDECAR (managed)"

foreach ($Name in $Profile) {
    $ConfigPath = Join-Path $env:LOCALAPPDATA "hermes\profiles\$Name\config.yaml"
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        Write-Warning "Skipping missing Hermes profile: $Name"
        continue
    }

    $Config = Get-Content -Raw -LiteralPath $ConfigPath
    $Backup = "$ConfigPath.hermes-aec-backup"
    if (-not (Test-Path -LiteralPath $Backup)) { Copy-Item -LiteralPath $ConfigPath -Destination $Backup }
    $Config = [regex]::Replace($Config, '(?ms)^  # BEGIN HERMES AEC SIDECAR \(managed\)\r?\n.*?^  # END HERMES AEC SIDECAR \(managed\)\r?\n?', '')
    # Remove pre-v1 unmarked registration and hide the direct Rhino script escape hatches.
    $Config = [regex]::Replace($Config, '(?ms)^  hermes_aec:\r?\n(?:(?!^  [A-Za-z0-9_-]+:).)*(?=^  [A-Za-z0-9_-]+:|\z)', '')
    $Config = [regex]::Replace($Config, '(?m)^\s{8}- (run_python|run_csharp)\r?\n?', '')

    $Block = @"
$Begin
  hermes_aec:
    command: $ServerYaml
    args: []
    env:
      HERMES_AEC_CONFIG_VERSION: "1"
      HERMES_AEC_RHINO_URL: http://127.0.0.1:$RhinoPort/
    connect_timeout: 30
    timeout: 320
    enabled: true
    tools:
      include:
        - rhino_scene_query
        - rhino_apply_operations
        - rhino_verify_transaction
        - rhino_health
$End
"@
    $Config = $Config.TrimEnd() + "`r`n" + $Block.TrimEnd() + "`r`n"
    Set-Content -LiteralPath $ConfigPath -Value $Config -Encoding utf8
    Write-Host "HERMES_AEC_REGISTERED profile=$Name config_version=1 rhino_port=$RhinoPort"
}
