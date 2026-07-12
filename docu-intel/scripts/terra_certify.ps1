[CmdletBinding()]
param(
    [switch]$Resume,
    [switch]$SkipFrontend,
    [switch]$SkipDocker,
    [switch]$RunSlowOcr,
    [switch]$KeepTemporaryDatabase,
    [string]$ArtifactsDirectory = "data/terra-certification"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepositoryRoot
$ArtifactsDirectory = [IO.Path]::GetFullPath((Join-Path $RepositoryRoot $ArtifactsDirectory))
New-Item -ItemType Directory -Force -Path $ArtifactsDirectory | Out-Null
$StatePath = Join-Path $ArtifactsDirectory "state.json"

if ($Resume -and (Test-Path $StatePath)) {
    $State = Get-Content -Raw -Path $StatePath | ConvertFrom-Json -AsHashtable
} else {
    $State = @{
        run_id = "terra-cert-$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))"
        started_at = [DateTime]::UtcNow.ToString("o")
        stages = @{}
    }
}

function Save-State {
    $State.updated_at = [DateTime]::UtcNow.ToString("o")
    $State | ConvertTo-Json -Depth 8 | Set-Content -Path $StatePath -Encoding utf8
}

function Invoke-CertificationStage {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$Action
    )

    if ($Resume -and $State.stages.ContainsKey($Name) -and $State.stages[$Name].status -eq "passed") {
        Write-Host "[$Name] already passed in $StatePath; skipping because -Resume was requested."
        return
    }

    $LogPath = Join-Path $ArtifactsDirectory "$Name.log"
    $State.stages[$Name] = @{
        status = "running"
        started_at = [DateTime]::UtcNow.ToString("o")
        log = $LogPath
    }
    Save-State

    Write-Host "[$Name] starting"
    try {
        & $Action *>&1 | Tee-Object -FilePath $LogPath
        if ($LASTEXITCODE -ne 0) {
            throw "Command exited with $LASTEXITCODE"
        }
        $State.stages[$Name].status = "passed"
    } catch {
        $State.stages[$Name].status = "failed"
        $State.stages[$Name].error = $_.Exception.Message
        throw
    } finally {
        $State.stages[$Name].ended_at = [DateTime]::UtcNow.ToString("o")
        Save-State
    }
}

function Invoke-Docker {
    param([Parameter(Mandatory)][string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') exited with $LASTEXITCODE"
    }
}

Invoke-CertificationStage "baseline" {
    git diff --check
    python -m compileall -q backend/app
    Push-Location backend
    try {
        python -m pytest -q tests/test_project_path_resolver.py tests/test_classification.py tests/test_mass_ingestion.py
    } finally {
        Pop-Location
    }
}

Invoke-CertificationStage "tenant-isolation" {
    Push-Location backend
    try {
        python -m pytest -q tests/test_tenant_deny_by_default.py tests/test_tenant_deny_by_default_exhaustive.py tests/test_tenant_access.py
    } finally {
        Pop-Location
    }
}

Invoke-CertificationStage "backend-suite" {
    Push-Location backend
    try {
        python -m pytest -q tests
    } finally {
        Pop-Location
    }
}

if (-not $SkipFrontend) {
    Invoke-CertificationStage "frontend-build" { npm --prefix frontend run build }
    Invoke-CertificationStage "frontend-tests" { npm --prefix frontend run test }
}

if (-not $SkipDocker) {
    $TemporaryDatabase = "$($State.run_id -replace '[^a-zA-Z0-9_]', '_').ToLowerInvariant()"
    if ($TemporaryDatabase -notmatch '^terra_cert_[a-z0-9_]+$') {
        throw "Refusing to use unsafe temporary database name: $TemporaryDatabase"
    }
    $Password = if ($env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD } else { "app" }
    $TemporaryDatabaseUrl = "postgresql+psycopg://app:$Password@postgres:5432/$TemporaryDatabase"

    try {
        Invoke-CertificationStage "postgres-create" {
            Invoke-Docker @("compose", "exec", "-T", "postgres", "psql", "-U", "app", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", "CREATE DATABASE $TemporaryDatabase")
        }
        Invoke-CertificationStage "postgres-migrations" {
            Invoke-Docker @("compose", "run", "--rm", "--no-deps", "-e", "DATABASE_URL=$TemporaryDatabaseUrl", "migrate")
        }
        Invoke-CertificationStage "postgres-e2e" {
            $mount = "${RepositoryRoot}/backend:/workspace:ro"
            $slow = if ($RunSlowOcr) { "RUN_SLOW_OCR_TESTS=1 " } else { "" }
            Invoke-Docker @("compose", "run", "--rm", "--no-deps", "--entrypoint", "sh", "-v", $mount, "-w", "/workspace", "-e", "DATABASE_URL=$TemporaryDatabaseUrl", "backend", "-lc", "${slow}EMBEDDING_PROVIDER=local_hash EMBEDDING_DIMENSIONS=1024 python -m pytest -q tests/test_terra_project_lifecycle_e2e.py tests/test_ocr_cascade.py tests/test_ocr_engine_tracking.py tests/test_ocr_golden.py tests/test_ocr_init_warmup.py tests/test_ocr_language.py tests/test_ocr_paddle.py tests/test_ocr_postprocess.py tests/test_ocr_preprocess.py tests/test_ocr_review.py -p no:cacheprovider")
        }
        Invoke-CertificationStage "docker-health" { Invoke-Docker @("compose", "ps") }
    } finally {
        if (-not $KeepTemporaryDatabase) {
            Write-Host "Removing owned temporary database $TemporaryDatabase"
            & docker compose exec -T postgres psql -U app -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $TemporaryDatabase WITH (FORCE)"
        }
    }
}

$State.completed_at = [DateTime]::UtcNow.ToString("o")
Save-State
Write-Host "Certification completed. Evidence: $ArtifactsDirectory"
