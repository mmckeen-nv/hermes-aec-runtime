$ErrorActionPreference = "Stop"

Clear-Host
Write-Host "Hermes + Rhino End-to-End Test" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan
Write-Host ""

$StatePath = Join-Path $env:LOCALAPPDATA "hermes\aec-demos\deployment.json"
if (-not (Test-Path -LiteralPath $StatePath)) {
    throw "AEC demos are not deployed. Run Deploy-AECDemos.ps1 first."
}

$State = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
$Launcher = Join-Path $State.platform_root "Launch-AECDemo.ps1"
if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "Deployed AEC launcher was not found at $Launcher"
}

$Prompt = @"
Use Rhino MCP only; do not use computer use or foreground UI automation. Inspect the active Cliff House model, identify the swimming pool boundary, and build a continuous 1.2 metre-high safety fence around the pool with a 1.0 metre offset and one clearly identifiable gate. Preserve the existing house and pool geometry. Verify the resulting fence height, continuity, offset, and object count in Rhino before reporting completion. Return a concise execution summary with the created object IDs and verification evidence.
"@

Set-Clipboard -Value $Prompt.Trim()
Write-Host "Starting a fresh Cliff House working copy, Rhino MCP, and Hermes..." -ForegroundColor Gray
& $Launcher -Demo Modification

Write-Host ""
Write-Host "READY" -ForegroundColor Green
Write-Host "The real workload is on your clipboard." -ForegroundColor Cyan
Write-Host "1. Switch to Hermes."
Write-Host "2. Paste the prompt into the modification profile."
Write-Host "3. Return here and press Enter immediately before submitting it."
Read-Host | Out-Null

$StartedAt = Get-Date
$Timer = [System.Diagnostics.Stopwatch]::StartNew()
Write-Host ""
Write-Host "TIMER RUNNING: $($StartedAt.ToString('HH:mm:ss.fff'))" -ForegroundColor Yellow
Write-Host "Submit the Hermes request now. When Hermes has verified the Rhino geometry, return here and press Enter."
Read-Host | Out-Null
$Timer.Stop()

$FinishedAt = Get-Date
Write-Host ""
Write-Host "END-TO-END RESULT" -ForegroundColor Cyan
Write-Host ("Started:  {0}" -f $StartedAt.ToString("HH:mm:ss.fff"))
Write-Host ("Finished: {0}" -f $FinishedAt.ToString("HH:mm:ss.fff"))
Write-Host ("Elapsed:  {0:N2} seconds ({1:N2} minutes)" -f $Timer.Elapsed.TotalSeconds, $Timer.Elapsed.TotalMinutes) -ForegroundColor Green
Write-Host ""
Write-Host "This result includes model inference, MCP calls, Rhino execution, and Hermes verification." -ForegroundColor Gray
Write-Host "Press Enter to close."
Read-Host | Out-Null

