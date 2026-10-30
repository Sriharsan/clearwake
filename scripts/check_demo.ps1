# Runs the four demo cases against the rehearsal gateway and prints PASS or FAIL for each.
# Rehearsal only: fake provider, synthetic records, no network or model calls.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "py"; $pyArgs = @("-3.12") } else { $pyArgs = @() }
& $python @pyArgs (Join-Path $PSScriptRoot "check_demo.py")
exit $LASTEXITCODE
