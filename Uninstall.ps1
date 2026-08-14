[CmdletBinding(SupportsShouldProcess)]
param(
    [string[]]$Profile = @("cliff-house-modifications-windows", "cliff-house-full-build-windows"),
    [switch]$KeepEnvironment
)

$ErrorActionPreference = "Stop"
foreach ($Name in $Profile) {
    $ConfigPath = Join-Path $env:LOCALAPPDATA "hermes\profiles\$Name\config.yaml"
    if (-not (Test-Path -LiteralPath $ConfigPath)) { continue }
    $Config = Get-Content -Raw -LiteralPath $ConfigPath
    $Config = [regex]::Replace($Config, '(?ms)^  # BEGIN HERMES AEC SIDECAR \(managed\)\r?\n.*?^  # END HERMES AEC SIDECAR \(managed\)\r?\n?', '')
    if ($PSCmdlet.ShouldProcess($ConfigPath, "Remove managed Hermes AEC registration")) {
        Set-Content -LiteralPath $ConfigPath -Value ($Config.TrimEnd() + "`r`n") -Encoding utf8
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
