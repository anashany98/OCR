$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Missing Docu-Intel .env file: $envFile"
}

$tokenLine = Get-Content -LiteralPath $envFile |
    Where-Object { $_ -match '^DWG_CONVERTER_BRIDGE_TOKEN=' } |
    Select-Object -Last 1
$token = ($tokenLine -split '=', 2)[1]
if ([string]::IsNullOrWhiteSpace($token) -or $token.Length -lt 32) {
    throw "DWG_CONVERTER_BRIDGE_TOKEN must be configured with at least 32 characters."
}

$alreadyRunning = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match 'oda_windows_bridge\.py'
}
if ($alreadyRunning) {
    exit 0
}

$log = Join-Path $env:TEMP "docu-intel-oda-bridge.log"
$errorLog = Join-Path $env:TEMP "docu-intel-oda-bridge.err.log"
Start-Process -FilePath python `
    -ArgumentList @("scripts/oda_windows_bridge.py", "--token", $token) `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $log `
    -RedirectStandardError $errorLog
