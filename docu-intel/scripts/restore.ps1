param(
  [Parameter(Mandatory=$true)]
  [string]$BackupDir,
  [string]$ComposeFile = "docker-compose.prod.yml",
  [string]$EnvFile = ".env.production",
  [switch]$IncludeRedis
)

$ErrorActionPreference = "Stop"
$dbBackup = Join-Path $BackupDir "docuintel.dump"
$filesBackup = Join-Path $BackupDir "files"
$redisBackup = Join-Path $BackupDir "redis-dump.rdb"

if (-not (Test-Path $dbBackup)) {
  throw "No existe backup PostgreSQL: $dbBackup"
}
if (-not (Test-Path $filesBackup)) {
  throw "No existe backup de archivos: $filesBackup"
}

docker compose --env-file $EnvFile -f $ComposeFile exec -T postgres pg_restore -U app -d docuintel --clean --if-exists < $dbBackup
robocopy $filesBackup data\files /MIR | Out-Null

if ($IncludeRedis) {
  if (-not (Test-Path -LiteralPath $redisBackup)) {
    throw "No existe backup Redis: $redisBackup. Backup sin -IncludeRedis o el flag no se uso al crearlo."
  }
  $redisLine = Get-Content -LiteralPath $EnvFile |
    Where-Object { $_ -match '^REDIS_PASSWORD=(.+)$' } |
    Select-Object -First 1
  if (-not $redisLine) {
    throw "REDIS_PASSWORD no encontrado en $EnvFile"
  }
  $redisPassword = ($redisLine -split '=', 2)[1].Trim()
  $redisContainer = (docker compose --env-file $EnvFile -f $ComposeFile ps -q redis)
  if (-not $redisContainer) {
    throw "Contenedor Redis no encontrado"
  }
  # Stop Redis, replace RDB, restart to load snapshot
  docker compose --env-file $EnvFile -f $ComposeFile stop redis | Out-Null
  docker cp $redisBackup "${redisContainer}:/data/dump.rdb" | Out-Null
  docker compose --env-file $EnvFile -f $ComposeFile start redis | Out-Null
  Write-Host "Redis RDB restaurado desde $redisBackup"
}

Write-Host "Restore aplicado desde $BackupDir"
