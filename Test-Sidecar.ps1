$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Executable = Join-Path $Root ".venv\Scripts\hermes-aec.exe"

Clear-Host
Write-Host "Hermes AEC Runtime Test" -ForegroundColor Cyan
Write-Host "=======================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $Executable)) {
    Write-Host "The runtime is not installed. Installing it now..." -ForegroundColor Yellow
    & (Join-Path $Root "Install.ps1")
}

Write-Host "Running: scene indexing -> context routing -> action assembly -> receipt" -ForegroundColor Gray
Write-Host "Request: put a safety fence around the pool" -ForegroundColor Gray
Write-Host ""

$Timer = [System.Diagnostics.Stopwatch]::StartNew()
& $Executable demo
$ExitCode = $LASTEXITCODE
$Timer.Stop()

Write-Host ""
if ($ExitCode -eq 0) {
    Write-Host "TEST PASSED" -ForegroundColor Green
} else {
    Write-Host "TEST FAILED (exit code $ExitCode)" -ForegroundColor Red
}
Write-Host ("Wall-clock time: {0:N2} ms ({1:N4} seconds)" -f $Timer.Elapsed.TotalMilliseconds, $Timer.Elapsed.TotalSeconds) -ForegroundColor Cyan
Write-Host ""
Write-Host "This test uses the safe mock adapter; it does not modify Rhino yet." -ForegroundColor Yellow
Write-Host "Press Enter to close, or type R and press Enter to run again." -ForegroundColor Gray
$Choice = Read-Host
if ($Choice -match "^[Rr]") {
    & $PSCommandPath
}

