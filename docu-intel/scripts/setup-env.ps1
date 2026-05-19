# Docu-Intel — Setup inicial para Windows + Docker Desktop
# Ejecutar: .\scripts\setup-env.ps1

$ErrorActionPreference = 'Stop'
$BASE = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
Set-Location $BASE

# Generar secreto seguro
function Get-SecureSecret {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 32
    $rng.GetBytes($bytes)
    return [Convert]::ToBase64String($bytes) -replace '\+', 'x' -replace '/', 'X'
}

Write-Host ""
Write-Host "=== Docu-Intel Setup: Windows + Docker Desktop ===" -ForegroundColor Cyan
Write-Host ""

# 1. Preguntar modelo de IA
Write-Host "1. CONFIGURACION DE IA" -ForegroundColor Yellow
Write-Host "   Ollama: corre en tu PC, gratuito, necesita RAM (4-8GB para modelos)" -ForegroundColor Gray
Write-Host "   LM Studio: igual que Ollama, interfaz grafica incluida, mejor para principiantes" -ForegroundColor Gray
Write-Host "   Ninguno: solo OCR/extraction, sin chat ni busqueda semantica" -ForegroundColor Gray
Write-Host ""

$aiChoice = Read-Host "   Elige: [1] Ollama  [2] LM Studio  [3] Sin IA  (1/2/3)"
$aiChoice = $aiChoice.Trim()

# 2. Preguntar si quiere busqueda semantica
Write-Host ""
Write-Host "2. BUSQUEDA SEMANTICA" -ForegroundColor Yellow
Write-Host "   Con semantica: busca por significado (ej: 'presupuesto de fontaneria')" -ForegroundColor Gray
Write-Host "   Sin semantica: busca por texto exacto (mas rapido, menos preciso)" -ForegroundColor Gray
$semanticChoice = Read-Host "   quieres busqueda semantica real? [s/n]"
$semanticChoice = ($semanticChoice.Trim() -eq 's')

# 3. Generar secretos
Write-Host ""
Write-Host "3. Generando secretos seguros..." -ForegroundColor Yellow
$pgPassword = Get-SecureSecret
$redisPassword = Get-SecureSecret
$jwtSecret = Get-SecureSecret

Write-Host "   PostgreSQL password: OK" -ForegroundColor Green
Write-Host "   Redis password: OK" -ForegroundColor Green
Write-Host "   JWT secret: OK" -ForegroundColor Green

# 4. Preguntar passwords de admin
Write-Host ""
Write-Host "4. USUARIO ADMIN" -ForegroundColor Yellow
$adminEmail = Read-Host "   Email del admin [admin@docuintel.local]"
if (-not $adminEmail) { $adminEmail = "admin@docuintel.local" }
$adminPassword = Read-Host "   Contrasena del admin (min 12 chars)" -AsSecureString
$adminPasswordPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($adminPassword))

# 5. Preguntar dominio
Write-Host ""
Write-Host "5. DOMINIO / ACCESO" -ForegroundColor Yellow
$corsOrigin = Read-Host "   Dominio publicoo IP (Enter para http://localhost:8080)"
if (-not $corsOrigin) { $corsOrigin = "http://localhost:8080" }

# 6. Determinar URL de IA
if ($aiChoice -eq "1") {
    $aiBaseUrl = "http://host.docker.internal:11434/v1"
    $aiModel = "llama3.2"
} elseif ($aiChoice -eq "2") {
    $aiBaseUrl = "http://host.docker.internal:1234/v1"
    $aiModel = "qwen2.5-32b-instruct"
} else {
    $aiBaseUrl = ""
    $aiModel = ""
}

# 7. Determinar embedding
if ($semanticChoice) {
    $embeddingProvider = "openai"
    $embeddingBaseUrl = $aiBaseUrl
    $embeddingModel = "nomic-embed-text"
    $embeddingDimensions = 768
    $embeddingFallback = "true"
} else {
    $embeddingProvider = "local_hash"
    $embeddingBaseUrl = ""
    $embeddingModel = "bge-m3"
    $embeddingDimensions = 1024
    $embeddingFallback = "true"
}

# 8. Escribir .env.production
Write-Host ""
Write-Host "6. Escribiendo .env.production..." -ForegroundColor Yellow

$envContent = @"
# Docu-Intel production environment — Windows + Docker Desktop
# Generado automaticamente por scripts/setup-env.ps1

ENVIRONMENT=production

# ————————————————————————————————
# Base de datos
# ————————————————————————————————
POSTGRES_PASSWORD=$pgPassword
DATABASE_URL=postgresql+psycopg://app:${pgPassword}@postgres:5432/docuintel
REDIS_PASSWORD=$redisPassword
REDIS_URL=redis://:${redisPassword}@redis:6379/0
RATE_LIMIT_STORAGE_URI=redis://:${redisPassword}@redis:6379/0

# ————————————————————————————————
# Archivos y directorios
# ————————————————————————————————
FILES_DIR=/app/data/files
INPUT_DIR=/app/data/input
SCAN_INTERVAL_SECONDS=300
INGESTION_STABLE_SECONDS=60
INGESTION_MAX_PENDING_JOBS=500
FILE_STORAGE_STRATEGY=auto
ALLOWED_FILE_EXTENSIONS=[".pdf",".png",".jpg",".jpeg",".tif",".tiff",".bmp",".webp",".xls",".xlsx",".xlsm",".csv",".tsv",".txt",".log",".eml"]
MAX_UPLOAD_SIZE_MB=200
MAX_PDF_PAGES=500
MAX_IMAGE_MEGAPIXELS=80
MAX_EXCEL_ROWS=100000
MAX_EXCEL_SHEETS=50
PDF_OCR_DPI=144
VECTOR_STORE=pgvector

# ————————————————————————————————
# Watcher de ingestion
# ————————————————————————————————
WATCHER_ENABLED=true
WATCHER_BACKEND=polling
WATCHER_RECURSIVE=true
WATCHER_POLL_SECONDS=10
WATCHER_SETTLE_SECONDS=30
WATCHER_RESCAN_INTERVAL_SECONDS=1800
WATCHER_MAX_FILES_PER_TICK=20

# ————————————————————————————————
# Seguridad
# ————————————————————————————————
CORS_ORIGINS=["${corsOrigin}"]
JWT_SECRET=$jwtSecret
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=strict
AUTH_LOGIN_RATE_LIMIT=10/minute

# ————————————————————————————————
# Admin inicial
# ————————————————————————————————
ADMIN_EMAIL=${adminEmail}
ADMIN_PASSWORD=${adminPasswordPlain}
ADMIN_NAME=Administrador

# ————————————————————————————————
# IA — Chat (Ollama / LM Studio / OpenAI)
# ————————————————————————————————
AI_PROVIDER=local_openai_compatible
AI_BASE_URL=${aiBaseUrl}
AI_MODEL=${aiModel}
AI_API_KEY=

# ————————————————————————————————
# OCR
# ————————————————————————————————
OCR_ENGINE=paddleocr
ENABLE_DOTS_MOCR=false

# ————————————————————————————————
# Embeddings
# ————————————————————————————————
EMBEDDING_PROVIDER=${embeddingProvider}
EMBEDDING_BASE_URL=${embeddingBaseUrl}
EMBEDDING_MODEL=${embeddingModel}
EMBEDDING_API_KEY=
EMBEDDING_DIMENSIONS=${embeddingDimensions}
EMBEDDING_TIMEOUT_SECONDS=30
EMBEDDING_FALLBACK_TO_HASH=${embeddingFallback}

# ————————————————————————————————
# Integracion
# ————————————————————————————————
INTEGRATION_CLIENTS=
INTEGRATION_ENQUEUE_UPLOADS=true
INTEGRATION_RATE_LIMIT_PER_MINUTE=120
INTEGRATION_SESSION_EXPIRE_SECONDS=3600
INTEGRATION_WEBHOOK_URL=
INTEGRATION_WEBHOOK_SECRET=
INTEGRATION_WEBHOOK_EVENTS=["document.processed","document.failed","document.needs_review","job.finished","docuintel.webhook_test"]

# ————————————————————————————————
# Workers
# ————————————————————————————————
WORKER_FAST_CONCURRENCY=2
WORKER_MAINTENANCE_CONCURRENCY=1
OCR_WORKER_CONCURRENCY=1
APP_UID=10001
APP_GID=10001

# ————————————————————————————————
# Frontend
# ————————————————————————————————
VITE_API_BASE_URL=/api
VITE_ENABLE_TENANT_ADMIN=false
"@

$envContent | Out-File -FilePath ".env.production" -Encoding UTF8 -NoNewline
Write-Host "   .env.production escrito" -ForegroundColor Green

# 9. Crear carpetas
Write-Host ""
Write-Host "7. Creando estructura de carpetas..." -ForegroundColor Yellow
$folders = @(
    "data\files",
    "data\input\presupuestos",
    "data\input\pedidos",
    "data\input\facturas",
    "data\input\planos",
    "data\input\imagenes",
    "data\input\otros",
    "backups"
)
foreach ($folder in $folders) {
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
}
Write-Host "   Carpetas creadas" -ForegroundColor Green

# 10. Instrucciones finales
Write-Host ""
Write-Host "=== Setup completado ===" -ForegroundColor Cyan
Write-Host ""

if ($aiChoice -eq "1") {
    Write-Host "   SIGUIENTE PASO — Instalar Ollama:" -ForegroundColor Yellow
    Write-Host "   1. Descargar: https://ollama.com/download/windows" -ForegroundColor White
    Write-Host "   2. Instalar y abrir (corre en segundo plano)" -ForegroundColor White
    Write-Host "   3. powershell: ollama pull llama3.2" -ForegroundColor White
    Write-Host "   4. powershell: ollama pull nomic-embed-text" -ForegroundColor White
    Write-Host "   5. python -m alembic upgrade head" -ForegroundColor White
} elseif ($aiChoice -eq "2") {
    Write-Host "   SIGUIENTE PASO — Instalar LM Studio:" -ForegroundColor Yellow
    Write-Host "   1. Descargar: https://lmstudio.ai/" -ForegroundColor White
    Write-Host "   2. Instalar, buscar y descargar un modelo (ej: Llama 3.2)" -ForegroundColor White
    Write-Host "   3. En LM Studio: Server tab > Start server (puerto 1234)" -ForegroundColor White
    Write-Host "   4. Descargar: ollama pull nomic-embed-text (para embeddings)" -ForegroundColor White
    Write-Host "   5. python -m alembic upgrade head" -ForegroundColor White
} else {
    Write-Host "   SIGUIENTE PASO:" -ForegroundColor Yellow
    Write-Host "   1. docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build" -ForegroundColor White
    Write-Host "   2. docker compose exec backend python -m alembic upgrade head" -ForegroundColor White
    Write-Host "   3. docker compose exec backend python scripts/create_admin.py" -ForegroundColor White
}

Write-Host ""
Write-Host "   Frontend: http://localhost:8080" -ForegroundColor White
Write-Host "   API:      http://localhost:8000" -ForegroundColor White
Write-Host "   Docs:     http://localhost:8000/docs" -ForegroundColor White