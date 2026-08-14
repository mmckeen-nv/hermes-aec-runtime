[CmdletBinding()]
param(
    [string[]]$Profile = @("cliff-house-modifications-windows", "cliff-house-full-build-windows"),
    [int]$RhinoPort = 10500
)

$ErrorActionPreference = "Stop"
$Server = Join-Path $PSScriptRoot ".venv\Scripts\hermes-aec-mcp.exe"
if (-not (Test-Path -LiteralPath $Server)) {
    throw "Sidecar is not installed. Run Install.ps1 first."
}
$ServerYaml = $Server.Replace("\", "/")

foreach ($Name in $Profile) {
    $ConfigPath = Join-Path $env:LOCALAPPDATA "hermes\profiles\$Name\config.yaml"
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        Write-Warning "Skipping missing Hermes profile: $Name"
        continue
    }

    $Config = Get-Content -Raw -LiteralPath $ConfigPath
    $Config = [regex]::Replace(
        $Config,
        '(?ms)^  hermes_aec:\r?\n(?:(?!^  [A-Za-z0-9_-]+:).)*(?=^  [A-Za-z0-9_-]+:|\z)',
        ''
    )
    # Hide raw scripting primitives from Hermes. The sidecar still reaches
    # them internally and wraps mutations in receipts and rollback handling.
    $Config = [regex]::Replace($Config, '(?m)^\s{8}- run_python\r?\n?', '')
    $Config = [regex]::Replace($Config, '(?m)^\s{8}- run_csharp\r?\n?', '')

    $Block = @"
  hermes_aec:
    command: $ServerYaml
    args: []
    env:
      HERMES_AEC_RHINO_URL: http://127.0.0.1:$RhinoPort/
    connect_timeout: 30
    timeout: 320
    enabled: true
    tools:
      include:
        - rhino_scene_preprocessing
        - rhino_execute_python
        - rhino_verify
"@
    $Config = $Config.TrimEnd() + "`r`n" + $Block.TrimEnd() + "`r`n"
    Set-Content -LiteralPath $ConfigPath -Value $Config -Encoding utf8
    Write-Host "HERMES_AEC_REGISTERED profile=$Name rhino_port=$RhinoPort"
}

