param(
  [Parameter(Mandatory=$true)]
  [string]$SourceDir,
  [string]$DestinationDir = "data\input",
  [string]$LogDir = "logs\imports"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $SourceDir)) {
  throw "No existe SourceDir: $SourceDir"
}

New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $LogDir "sync_incremental_$timestamp.log"

robocopy $SourceDir $DestinationDir /E /XO /FFT /R:2 /W:5 /TEE /LOG:$logFile
$code = $LASTEXITCODE
if ($code -gt 7) {
  throw "Sync incremental fallo con codigo Robocopy $code. Log: $logFile"
}

Write-Host "Sync incremental completado. Log: $logFile"
