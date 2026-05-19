param(
  [string]$ComposeFile = "docker-compose.prod.yml",
  [string]$EnvFile = ".env.production",
  [string]$BackupDir = "backups",
  [int]$RetentionDays = 14,
  [int64]$MinDumpBytes = 1024
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$target = Join-Path $BackupDir $timestamp
New-Item -ItemType Directory -Force -Path $target | Out-Null

$dbBackup = Join-Path $target "docuintel.dump"
$filesBackup = Join-Path $target "files"
$logFile = Join-Path $target "backup.log"
$manifestFile = Join-Path $target "manifest.json"

try {
  docker compose --env-file $EnvFile -f $ComposeFile exec -T postgres pg_dump -U app -d docuintel -Fc > $dbBackup
  $dump = Get-Item -LiteralPath $dbBackup
  if ($dump.Length -lt $MinDumpBytes) {
    throw "Backup PostgreSQL demasiado pequeno: $($dump.Length) bytes"
  }

  robocopy data\files $filesBackup /MIR /R:2 /W:5 /LOG+:$logFile | Out-Null
  if ($LASTEXITCODE -gt 7) {
    throw "Robocopy fallo con codigo $LASTEXITCODE"
  }

  $files = Get-ChildItem -LiteralPath $filesBackup -Recurse -File -ErrorAction SilentlyContinue
  $manifest = [ordered]@{
    created_at = (Get-Date).ToString("o")
    compose_file = $ComposeFile
    env_file = $EnvFile
    postgres_dump = "docuintel.dump"
    postgres_dump_bytes = $dump.Length
    files_count = @($files).Count
    files_bytes = (@($files) | Measure-Object -Property Length -Sum).Sum
  }
  $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestFile -Encoding UTF8

  if ($RetentionDays -gt 0 -and (Test-Path -LiteralPath $BackupDir)) {
    Get-ChildItem -LiteralPath $BackupDir -Directory |
      Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$RetentionDays) } |
      Remove-Item -Recurse -Force
  }

  Write-Host "Backup creado en $target"
} catch {
  "[$((Get-Date).ToString("o"))] ERROR: $($_.Exception.Message)" | Add-Content -LiteralPath $logFile
  throw
}
