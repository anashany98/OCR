param(
  [string]$ComposeFile = "docker-compose.prod.yml",
  [string]$EnvFile = ".env.production",
  [int]$HealthTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

# Verify Docker is running
try {
  docker info 2>&1 | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Docker no esta corriendo" }
} catch {
  throw "Docker no esta disponible o no esta corriendo. Inicia Docker Desktop primero."
}

# Verify compose file exists
if (-not (Test-Path -LiteralPath $ComposeFile)) {
  throw "Compose file not found: $ComposeFile"
}

# Verify env file exists
if (-not (Test-Path -LiteralPath $EnvFile)) {
  throw "Env file not found: $EnvFile"
}

New-Item -ItemType Directory -Force -Path "data\files" | Out-Null
New-Item -ItemType Directory -Force -Path "data\input" | Out-Null
New-Item -ItemType Directory -Force -Path "backups" | Out-Null

$env:DOCUINTEL_ENV_FILE = $EnvFile
docker compose --env-file $EnvFile -f $ComposeFile up -d --build

$deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
do {
  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8000/health" -TimeoutSec 5
    if ($response.StatusCode -eq 200) {
      Write-Host "Docu-Intel listo en http://localhost:8080"
      exit 0
    }
  } catch {
    Start-Sleep -Seconds 5
  }
} while ((Get-Date) -lt $deadline)

throw "Docu-Intel no respondio en /health antes de $HealthTimeoutSeconds segundos"
