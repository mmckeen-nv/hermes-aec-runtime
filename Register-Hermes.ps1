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

function Set-AtomicText([string]$Path, [string]$Value) {
    $Directory = Split-Path -Parent $Path
    $Temporary = Join-Path $Directory ("." + [IO.Path]::GetFileName($Path) + "." + [guid]::NewGuid().ToString("N") + ".tmp")
    try {
        Set-Content -LiteralPath $Temporary -Value $Value -Encoding utf8NoBOM
        Move-Item -LiteralPath $Temporary -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $Temporary) { Remove-Item -LiteralPath $Temporary -Force }
    }
}

foreach ($Name in $Profile) {
    $ConfigPath = Join-Path $env:LOCALAPPDATA "hermes\profiles\$Name\config.yaml"
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        Write-Warning "Skipping missing Hermes profile: $Name"
        continue
    }

    $Config = Get-Content -Raw -LiteralPath $ConfigPath
    $BackupDirectory = Join-Path (Split-Path -Parent $ConfigPath) ".hermes-aec-backups"
    New-Item -ItemType Directory -Force -Path $BackupDirectory | Out-Null
    $Backup = Join-Path $BackupDirectory ("config." + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffffffZ") + ".yaml")
    Copy-Item -LiteralPath $ConfigPath -Destination $Backup
    $Config = [regex]::Replace($Config, '(?ms)^  # BEGIN HERMES AEC SIDECAR \(managed\)\r?\n.*?^  # END HERMES AEC SIDECAR \(managed\)\r?\n?', '')
    # Remove pre-v1 unmarked registration and hide the direct Rhino script escape hatches.
    $Config = [regex]::Replace($Config, '(?ms)^  hermes_aec:\r?\n(?:(?!^  [A-Za-z0-9_-]+:).)*(?=^  [A-Za-z0-9_-]+:|\z)', '')
    $Config = [regex]::Replace($Config, '(?m)^\s{8}- (run_python|run_csharp)\r?\n?', '')

    $ToolLines = @(
        "        - aec_workflow_plan"
        "        - aec_run_workflow"
        "        - route_aec_request",
        "        - rhino_scene_query",
        "        - rhino_apply_operations",
        "        - rhino_verify_transaction",
        "        - rhino_health"
        "        - blender_scene_query"
        "        - blender_apply_operations"
        "        - blender_validate_handoff"
        "        - blender_proof_and_recovery"
        "        - workflow_memory_promote"
        "        - workflow_memory_query"
        "        - flight_recorder_record"
    )
    if ($Name -eq "cliff-house-full-build-windows") {
        $ToolLines += "        - rhino_execute_python"
    }
    $ToolBlock = $ToolLines -join "`r`n"
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
$ToolBlock
$End
"@
    if ($Config -notmatch '(?m)^mcp_servers:\s*$') { throw "Hermes profile has no mcp_servers mapping: $ConfigPath (backup: $Backup)" }
    $Section = [regex]::Match($Config, '(?ms)^mcp_servers:\s*\r?\n.*?(?=^[A-Za-z0-9_-]+:\s*(?:#.*)?$|\z)')
    if (-not $Section.Success) { throw "Could not safely locate mcp_servers mapping: $ConfigPath (backup: $Backup)" }
    $UpdatedSection = $Section.Value.TrimEnd() + "`r`n" + $Block.TrimEnd() + "`r`n"
    $Config = $Config.Substring(0, $Section.Index) + $UpdatedSection + $Config.Substring($Section.Index + $Section.Length)
    Set-AtomicText -Path $ConfigPath -Value ($Config.TrimEnd() + "`r`n")
    Write-Host "HERMES_AEC_REGISTERED profile=$Name config_version=1 rhino_port=$RhinoPort backup=$Backup"
}
