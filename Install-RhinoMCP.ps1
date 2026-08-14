[CmdletBinding()]
param(
    [string]$Version = "0.4.0-aec.2",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$PluginGuid = "ca441fe8-afc4-43a4-bee5-53e65030d229"
$Archive = Join-Path $PSScriptRoot "vendor\aec-rhinomcp-$Version-windows.zip"
$PluginRoot = Join-Path $env:APPDATA "McNeel\Rhinoceros\8.0\Plug-ins"
$Target = Join-Path $PluginRoot "AEC RhinoMCP ($PluginGuid)"

if (-not (Test-Path -LiteralPath $Archive)) {
    throw "Bundled AEC RhinoMCP archive is missing: $Archive"
}
if (Get-Process Rhino -ErrorAction SilentlyContinue) {
    throw "Close every Rhino instance before installing AEC RhinoMCP."
}

if (-not $SkipInstall) {
    New-Item -ItemType Directory -Force -Path $PluginRoot | Out-Null
    $Stage = Join-Path $env:TEMP ("aec-rhinomcp-stage-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $Stage | Out-Null
    try {
        Expand-Archive -LiteralPath $Archive -DestinationPath $Stage
        $StagedPlugin = Join-Path $Stage "aec-rhinomcp.rhp"
        if (-not (Test-Path -LiteralPath $StagedPlugin)) {
            throw "AEC RhinoMCP archive does not contain aec-rhinomcp.rhp at its root."
        }
        if (Test-Path -LiteralPath $Target) {
            $Backup = "$Target.backup.$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssfffZ'))"
            Move-Item -LiteralPath $Target -Destination $Backup
            Write-Host "RHINOMCP_PLUGIN_BACKUP path=$Backup"
        }
        Move-Item -LiteralPath $Stage -Destination $Target
        $Stage = $null
    }
    finally {
        if ($Stage -and (Test-Path -LiteralPath $Stage)) {
            Remove-Item -LiteralPath $Stage -Recurse -Force
        }
    }
}

$Plugin = Join-Path $Target "aec-rhinomcp.rhp"
if (-not (Test-Path -LiteralPath $Plugin)) {
    throw "AEC RhinoMCP plug-in was not installed at $Plugin."
}

Write-Host "RHINOMCP_PLUGIN_READY distribution=mmckeen-nv/aec-rhinomcp version=$Version guid=$PluginGuid plugin=$Plugin"
Write-Host "Restart Rhino and run AECMCPStart. The verified listener must be 127.0.0.1:1999."
