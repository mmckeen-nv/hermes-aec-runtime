[CmdletBinding()]
param(
    [string]$Package = "rhinomcp",
    [string]$Version = "0.3.2",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Yak = "C:\Program Files\Rhino 8\System\yak.exe"
if (-not (Test-Path -LiteralPath $Yak)) { throw "Rhino 8 Yak package manager was not found." }

if (-not $SkipInstall) {
    & $Yak install $Package $Version
    if ($LASTEXITCODE) { throw "Yak could not install $Package $Version (exit $LASTEXITCODE)." }
}

$PackageRoot = Join-Path $env:APPDATA "McNeel\Rhinoceros\packages\8.0\$Package\$Version"
$Plugin = Get-ChildItem -LiteralPath $PackageRoot -Filter *.rhp -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $Plugin) { throw "Installed package has no Rhino plugin under $PackageRoot." }

Write-Host "RHINOMCP_PLUGIN_READY package=$Package version=$Version plugin=$($Plugin.FullName)"
Write-Host "Restart Rhino, run AECMCPStart, and enter port 1999. If using upstream 0.3.2, run MCPStart instead."
Write-Host "The standalone Python MCP wrapper is not exposed to Hermes. If you need it for debugging, pin its dependency: uvx --with `"mcp<2`" --from `"rhinomcp[validation]==$Version`" rhinomcp"
