# One time PayPal SANDBOX setup: creates an order, waits for your sandbox buyer approval, captures it.
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "py"; $pyArgs = @("-3.12") } else { $pyArgs = @() }
& $python @pyArgs (Join-Path $PSScriptRoot "sandbox_setup.py")
exit $LASTEXITCODE
