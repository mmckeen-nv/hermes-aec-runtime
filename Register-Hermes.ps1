[CmdletBinding()]
param(
    [string[]]$Profile = @("cliff-house-modifications-windows", "cliff-house-full-build-windows"),
    [ValidateRange(1024, 65535)][int]$RhinoPort = 1999,
    [ValidateRange(1024, 65535)][int]$LegacyRhinoPort = 10500,
    [switch]$DisableLegacyFallback,
    [switch]$EnableLegacyFallback,
    [switch]$EnableBlender,
    [switch]$EnableComfyUI
)

$ErrorActionPreference = "Stop"
$Server = Join-Path $PSScriptRoot ".venv\Scripts\hermes-aec-mcp.exe"
if (-not (Test-Path -LiteralPath $Server)) { throw "Run Install.ps1 first." }
$ServerYaml = $Server.Replace("\", "/")
$BlenderCommand = Join-Path $env:LOCALAPPDATA "hermes\integrations\blender-mcp\blender-mcp.cmd"
$BlenderCommandYaml = $BlenderCommand.Replace("\", "/")
$HdriRoot = Join-Path $env:LOCALAPPDATA "hermes\integrations\blender-hdri\polyhaven-2k"
$HdriRootYaml = $HdriRoot.Replace("\", "/")
if ($EnableBlender -and -not (Test-Path -LiteralPath $BlenderCommand)) { throw "Blender was enabled but its managed MCP launcher is missing: $BlenderCommand" }
if ($EnableBlender -and -not (Test-Path -LiteralPath (Join-Path $HdriRoot "manifest.json"))) { throw "Blender was enabled but its managed HDRI library is missing: $HdriRoot" }
$Begin = "  # BEGIN HERMES AEC SIDECAR (managed)"
$End = "  # END HERMES AEC SIDECAR (managed)"

function Set-AtomicText([string]$Path, [string]$Value) {
    $Directory = Split-Path -Parent $Path
    $Temporary = Join-Path $Directory ("." + [IO.Path]::GetFileName($Path) + "." + [guid]::NewGuid().ToString("N") + ".tmp")
    try {
        [IO.File]::WriteAllText($Temporary, $Value, (New-Object Text.UTF8Encoding($false)))
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
    # Hermes must never bypass the sidecar and invoke RhinoMCP/raw scripts itself.
    $Config = [regex]::Replace($Config, '(?ms)^  rhino:\r?\n(?:(?!^  [A-Za-z0-9_-]+:).)*(?=^  [A-Za-z0-9_-]+:|\z)', '')
    $Config = [regex]::Replace($Config, '(?m)^\s{8}- (run_python|run_csharp)\r?\n?', '')

    $ToolLines = @(
        "        - aec_workflow_plan"
        "        - aec_run_workflow"
        "        - aec_runtime_health"
        "        - route_aec_request",
        "        - rhino_scene_query",
        "        - rhino_apply_operations",
        "        - rhino_verify_transaction",
        "        - rhino_health"
        "        - rhino_export_scene"
        "        - rhino_open_working_document"
        "        - rhino_viewport_state"
        "        - rhino_viewport_zoom_extents"
        "        - rhino_viewport_set_camera"
        "        - rhino_viewport_set_target"
        "        - rhino_viewport_orbit"
        "        - rhino_viewport_restore_named_view"
        "        - rhino_viewport_capture"
        "        - workflow_memory_promote"
        "        - workflow_memory_query"
        "        - flight_recorder_record"
    )
    if ($EnableBlender) {
        $ToolLines += @(
            "        - blender_scene_query"
            "        - blender_apply_operations"
            "        - blender_import_handoff"
            "        - blender_render_archviz"
            "        - blender_validate_handoff"
            "        - blender_proof_and_recovery"
        )
    }
    if ($EnableComfyUI) {
        $ToolLines += @(
            "        - comfyui_health"
            "        - comfyui_stylize_image"
        )
    }
    $ToolBlock = $ToolLines -join "`r`n"
    $Block = @"
$Begin
  hermes_aec:
    command: $ServerYaml
    args: []
    env:
      HERMES_AEC_CONFIG_VERSION: "2"
      HERMES_AEC_RHINOMCP_HOST: 127.0.0.1
      HERMES_AEC_RHINOMCP_PORT: "$RhinoPort"
      HERMES_AEC_LEGACY_RHINO_URL: http://127.0.0.1:$LegacyRhinoPort/
      HERMES_AEC_ENABLE_LEGACY_FALLBACK: "$(if ($EnableLegacyFallback -and -not $DisableLegacyFallback) { '1' } else { '0' })"
      HERMES_AEC_ENABLE_BLENDER: "$($EnableBlender.ToString().ToLower())"
      HERMES_AEC_BLENDER_COMMAND: "$BlenderCommandYaml"
      HERMES_AEC_BLENDER_ARGS: ""
      HERMES_AEC_HDRI_ROOT: "$HdriRootYaml"
      HERMES_AEC_ENABLE_COMFYUI: "$($EnableComfyUI.ToString().ToLower())"
      HERMES_AEC_COMFYUI_URL: "http://127.0.0.1:8188"
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
    Write-Host "HERMES_AEC_REGISTERED profile=$Name config_version=2 rhinomcp_port=$RhinoPort backup=$Backup"
}
