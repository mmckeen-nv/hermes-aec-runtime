[CmdletBinding(SupportsShouldProcess)]
param(
    [string[]]$Profile = @("cliff-house-modifications-windows", "cliff-house-full-build-windows"),
    [switch]$KeepEnvironment
)

$ErrorActionPreference = "Stop"
function Set-AtomicText([string]$Path, [string]$Value) {
    $Temporary = Join-Path (Split-Path -Parent $Path) ("." + [IO.Path]::GetFileName($Path) + "." + [guid]::NewGuid().ToString("N") + ".tmp")
    try {
        [IO.File]::WriteAllText($Temporary, $Value, (New-Object Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $Temporary -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $Temporary) { Remove-Item -LiteralPath $Temporary -Force }
    }
}
foreach ($Name in $Profile) {
    $ConfigPath = Join-Path $env:LOCALAPPDATA "hermes\profiles\$Name\config.yaml"
    if (-not (Test-Path -LiteralPath $ConfigPath)) { continue }
    $Config = Get-Content -Raw -LiteralPath $ConfigPath
    $Config = [regex]::Replace($Config, '(?ms)^  # BEGIN HERMES AEC SIDECAR \(managed\)\r?\n.*?^  # END HERMES AEC SIDECAR \(managed\)\r?\n?', '')
    if ($PSCmdlet.ShouldProcess($ConfigPath, "Remove managed Hermes AEC registration")) {
        $BackupDirectory = Join-Path (Split-Path -Parent $ConfigPath) ".hermes-aec-backups"
        New-Item -ItemType Directory -Force -Path $BackupDirectory | Out-Null
        $Backup = Join-Path $BackupDirectory ("config.pre-uninstall." + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffffffZ") + ".yaml")
        Copy-Item -LiteralPath $ConfigPath -Destination $Backup
        Set-AtomicText -Path $ConfigPath -Value ($Config.TrimEnd() + "`r`n")
    }
}
if (-not $KeepEnvironment) {
    foreach ($Leaf in @(".venv", ".runtime")) {
        $Target = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $Leaf))
        if (-not $Target.StartsWith([IO.Path]::GetFullPath($PSScriptRoot), [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe uninstall target: $Target" }
        if ((Test-Path -LiteralPath $Target) -and $PSCmdlet.ShouldProcess($Target, "Remove generated installation files")) {
            Remove-Item -LiteralPath $Target -Recurse -Force
        }
    }
}
Write-Host "HERMES_AEC_UNINSTALLED"
