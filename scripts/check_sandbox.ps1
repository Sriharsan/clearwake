# Four cases against the real PayPal SANDBOX. Prints PASS or FAIL for each. Add -LocalAI to use the local model.
param([switch]$LocalAI)
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "py"; $pyArgs = @("-3.12") } else { $pyArgs = @() }
$extra = @(); if ($LocalAI) { $extra += "--local-ai" }
& $python @pyArgs (Join-Path $PSScriptRoot "check_sandbox.py") @extra
exit $LASTEXITCODE
