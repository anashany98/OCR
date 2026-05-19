param(
  [Parameter(Mandatory=$true)]
  [string]$BackupDir,
  [string]$ComposeFile = "docker-compose.prod.yml",
  [string]$EnvFile = ".env.production"
)

$ErrorActionPreference = "Stop"
$dbBackup = Join-Path $BackupDir "docuintel.dump"
$filesBackup = Join-Path $BackupDir "files"

if (-not (Test-Path $dbBackup)) {
  throw "No existe backup PostgreSQL: $dbBackup"
}
if (-not (Test-Path $filesBackup)) {
  throw "No existe backup de archivos: $filesBackup"
}

docker compose --env-file $EnvFile -f $ComposeFile exec -T postgres pg_restore -U app -d docuintel --clean --if-exists < $dbBackup
robocopy $filesBackup data\files /MIR | Out-Null

Write-Host "Restore aplicado desde $BackupDir"
