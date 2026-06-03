param(
  [Parameter(Mandatory=$true)]
  [string]$BackupDir,
  [int64]$MinDumpBytes = 1024
)

$ErrorActionPreference = "Stop"

$manifestFile = Join-Path $BackupDir "manifest.json"
if (-not (Test-Path -LiteralPath $manifestFile)) {
  throw "No existe manifest de backup: $manifestFile"
}

$manifest = Get-Content -Raw -LiteralPath $manifestFile | ConvertFrom-Json
$dumpName = if ($manifest.postgres_dump) { [string]$manifest.postgres_dump } else { "docuintel.dump" }
$dbBackup = Join-Path $BackupDir $dumpName
$filesBackup = Join-Path $BackupDir "files"

if (-not (Test-Path -LiteralPath $dbBackup)) {
  throw "No existe backup PostgreSQL: $dbBackup"
}
if (-not (Test-Path -LiteralPath $filesBackup)) {
  throw "No existe backup de archivos: $filesBackup"
}

$dump = Get-Item -LiteralPath $dbBackup
if ($dump.Length -lt $MinDumpBytes) {
  throw "Backup PostgreSQL demasiado pequeno: $($dump.Length) bytes"
}
if ($manifest.postgres_dump_bytes -and [int64]$manifest.postgres_dump_bytes -ne $dump.Length) {
  throw "El tamano del dump no coincide con manifest.json"
}

$files = @(Get-ChildItem -LiteralPath $filesBackup -Recurse -File -ErrorAction SilentlyContinue)
$filesBytes = ($files | Measure-Object -Property Length -Sum).Sum
if ($null -eq $filesBytes) {
  $filesBytes = 0
}

if ($null -ne $manifest.files_count -and [int64]$manifest.files_count -ne $files.Count) {
  throw "El conteo de archivos no coincide con manifest.json"
}
if ($null -ne $manifest.files_bytes -and [int64]$manifest.files_bytes -ne [int64]$filesBytes) {
  throw "El tamano de archivos no coincide con manifest.json"
}

if ($manifest.include_redis -and [bool]$manifest.include_redis) {
  $redisName = if ($manifest.redis_dump) { [string]$manifest.redis_dump } else { "redis-dump.rdb" }
  $redisBackup = Join-Path $BackupDir $redisName
  if (-not (Test-Path -LiteralPath $redisBackup)) {
    throw "Manifest marca include_redis pero falta $redisBackup"
  }
  $redisFile = Get-Item -LiteralPath $redisBackup
  if ($redisFile.Length -lt 1) {
    throw "Backup Redis vacio: $($redisFile.Length) bytes"
  }
  if ($manifest.redis_dump_bytes -and [int64]$manifest.redis_dump_bytes -ne $redisFile.Length) {
    throw "El tamano del RDB no coincide con manifest.json"
  }
  Write-Host "  Redis RDB: $($redisFile.Length) bytes"
}

Write-Host "Backup verificado: $BackupDir"
