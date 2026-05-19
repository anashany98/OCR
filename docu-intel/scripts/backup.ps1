param(
  [string]$ComposeFile = "docker-compose.prod.yml",
  [string]$EnvFile = ".env.production",
  [string]$BackupDir = "backups"
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$target = Join-Path $BackupDir $timestamp
New-Item -ItemType Directory -Force -Path $target | Out-Null

$dbBackup = Join-Path $target "docuintel.dump"
$filesBackup = Join-Path $target "files"

docker compose --env-file $EnvFile -f $ComposeFile exec -T postgres pg_dump -U app -d docuintel -Fc > $dbBackup
robocopy data\files $filesBackup /MIR | Out-Null

Write-Host "Backup creado en $target"
