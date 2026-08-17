[CmdletBinding()]
param(
    [string]$Version = "0.4.0-aec.2",
    [switch]$SkipInstall,
    [string]$PluginRoot = (Join-Path $env:APPDATA "McNeel\Rhinoceros\8.0\Plug-ins")
)

$ErrorActionPreference = "Stop"
$PluginGuid = "ca441fe8-afc4-43a4-bee5-53e65030d229"
$Archive = Join-Path $PSScriptRoot "vendor\aec-rhinomcp-$Version-windows.zip"
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
Unblock-File -LiteralPath $Plugin -ErrorAction SilentlyContinue

# Rhino discovers third-party command names through this per-user registration. Copying an RHP
# alone is insufficient on a clean workstation and results in "Unknown command: AECMCPStart".
$RegistryPath = "HKCU:\Software\McNeel\Rhinoceros\8.0\Plug-ins\$PluginGuid"
$RegistryPluginPath = Join-Path $RegistryPath "PlugIn"
$RegistryCommandsPath = Join-Path $RegistryPath "CommandList"
New-Item -Path $RegistryPath -Force | Out-Null
New-ItemProperty -Path $RegistryPath -Name "LoadMode" -Value 2 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $RegistryPath -Name "Type" -Value 16 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $RegistryPath -Name "Name" -Value "aec-rhinomcp" -PropertyType String -Force | Out-Null
New-ItemProperty -Path $RegistryPath -Name "FileName" -Value $Plugin -PropertyType String -Force | Out-Null
New-ItemProperty -Path $RegistryPath -Name "EnglishName" -Value "aec-rhinomcp" -PropertyType String -Force | Out-Null
New-ItemProperty -Path $RegistryPath -Name "IsDotNETPlugIn" -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $RegistryPath -Name "Description" -Value "Hardened AEC fork of RhinoMCP" -PropertyType String -Force | Out-Null
New-Item -Path $RegistryPluginPath -Force | Out-Null
New-ItemProperty -Path $RegistryPluginPath -Name "FileName" -Value $Plugin -PropertyType String -Force | Out-Null
New-Item -Path $RegistryCommandsPath -Force | Out-Null
foreach ($Command in @("aecmcpstart", "aecmcpstop", "aecmcptest", "aecmcpversion")) {
    New-ItemProperty -Path $RegistryCommandsPath -Name $Command -Value "2;$Command" -PropertyType String -Force | Out-Null
}

$Metadata = @{
    schema_version = 1
    distribution = "mmckeen-nv/aec-rhinomcp"
    version = $Version
    guid = $PluginGuid
    plugin = $Plugin
} | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $Target "hermes-aec-install.json"), $Metadata + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))

Write-Host "RHINOMCP_PLUGIN_READY distribution=mmckeen-nv/aec-rhinomcp version=$Version guid=$PluginGuid plugin=$Plugin"
Write-Host "RHINOMCP_COMMANDS_REGISTERED discovery=root-filename commands=AECMCPStart,AECMCPStop,AECMCPTest,AECMCPVersion"
Write-Host "Restart Rhino and run AECMCPStart. The verified listener must be 127.0.0.1:1999."
