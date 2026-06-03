param(
  [string]$ComposeFile = "docker-compose.prod.yml",
  [string]$EnvFile = ".env.production",
  [string]$BackupDir = "backups",
  [int]$RetentionDays = 14,
  [int64]$MinDumpBytes = 1024,
  [switch]$IncludeRedis,
  [int]$RedisBgsaveWaitSeconds = 10
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$target = Join-Path $BackupDir $timestamp
New-Item -ItemType Directory -Force -Path $target | Out-Null

$dbBackup = Join-Path $target "docuintel.dump"
$filesBackup = Join-Path $target "files"
$redisBackup = Join-Path $target "redis-dump.rdb"
$logFile = Join-Path $target "backup.log"
$manifestFile = Join-Path $target "manifest.json"

$redisBytes = $null
$redisError = $null

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

  if ($IncludeRedis) {
    # Extract REDIS_PASSWORD from .env (required by redis-cli -a)
    $redisLine = Get-Content -LiteralPath $EnvFile |
      Where-Object { $_ -match '^REDIS_PASSWORD=(.+)$' } |
      Select-Object -First 1
    if (-not $redisLine) {
      throw "REDIS_PASSWORD no encontrado en $EnvFile. Imposible hacer backup de Redis."
    }
    $redisPassword = ($redisLine -split '=', 2)[1].Trim()

    $redisContainer = (docker compose --env-file $EnvFile -f $ComposeFile ps -q redis)
    if (-not $redisContainer) {
      throw "Contenedor Redis no encontrado. Levanta el stack antes de -IncludeRedis."
    }

    # Trigger background save and wait for completion
    docker exec $redisContainer redis-cli -a $redisPassword --no-auth-warning BGSAVE | Out-Null
    if ($LASTEXITCODE -ne 0) {
      throw "redis-cli BGSAVE fallo con codigo $LASTEXITCODE"
    }
    Start-Sleep -Seconds $RedisBgsaveWaitSeconds

    # Verify lastsave advanced past the trigger moment
    $lastSave = docker exec $redisContainer redis-cli -a $redisPassword --no-auth-warning LASTSAVE
    if ($LASTEXITCODE -ne 0) {
      throw "redis-cli LASTSAVE fallo con codigo $LASTEXITCODE"
    }

    # Copy RDB snapshot out of container
    docker cp "${redisContainer}:/data/dump.rdb" $redisBackup | Out-Null
    if ($LASTEXITCODE -ne 0) {
      throw "docker cp dump.rdb fallo con codigo $LASTEXITCODE"
    }
    $redisFile = Get-Item -LiteralPath $redisBackup
    $redisBytes = $redisFile.Length
    if ($redisBytes -lt 1) {
      throw "Backup Redis demasiado pequeno: $redisBytes bytes"
    }
    Write-Host "Redis RDB copiado: $redisBytes bytes (lastsave=$lastSave)"
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
    include_redis = [bool]$IncludeRedis
  }
  if ($IncludeRedis) {
    $manifest["redis_dump"] = "redis-dump.rdb"
    $manifest["redis_dump_bytes"] = $redisBytes
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
