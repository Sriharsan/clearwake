# One command demo: starts the Clearwake rehearsal server and opens it in the browser.
# Rehearsal only: fake provider, synthetic records, no network or model calls.
# Usage: .\run.ps1                 (normal refund, steps 1 and 4)
#        .\run.ps1 -Outcome lost-response   (steps 2 and 3)
param(
    [ValidateSet("completed", "pending", "lost-response")]
    [string]$Outcome = "completed",
    [int]$Port = 8810
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "py"; $pyArgs = @("-3.12") } else { $pyArgs = @() }
# A fresh database per run so every demo starts from a clean fictional case.
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$database = Join-Path $root "data\demo-$Outcome-$stamp\case.sqlite3"
Write-Host "REHEARSAL MODE. Fake provider, synthetic records. Outcome: $Outcome"
Write-Host "Database: $database"
Start-Job -ScriptBlock { param($url) Start-Sleep 2; Start-Process $url } -ArgumentList "http://127.0.0.1:$Port" | Out-Null
Push-Location $root
try { & $python @pyArgs -m clearwake --port $Port --database $database --rehearsal-outcome $Outcome }
finally { Pop-Location }
