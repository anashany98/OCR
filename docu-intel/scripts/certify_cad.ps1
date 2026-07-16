[CmdletBinding()]
param(
    [switch]$WithDocker,
    [string]$Corpus = "backend/tests/fixtures/cad",
    [string]$ArtifactsDirectory = "artifacts/cad"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepositoryRoot
New-Item -ItemType Directory -Force -Path $ArtifactsDirectory | Out-Null

function Invoke-Step([string]$Name, [scriptblock]$Action) {
    Write-Host "[$Name] starting"
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
    Write-Host "[$Name] passed"
}

Invoke-Step "diff-check" { git diff --check }
Invoke-Step "lint" { python -m ruff check backend/app }
Invoke-Step "format" { python -m ruff format --check backend/app }
Invoke-Step "compile" { python -m compileall -q backend/app scripts/benchmark_cad_ingestion.py scripts/reprocess_cad_documents.py }
Invoke-Step "unit-cad" {
    Push-Location backend
    try {
        python -m pytest -q tests/test_cad_structured_implementation.py tests/test_dxf.py tests/test_dwg_parser.py tests/test_plan_extraction.py tests/test_plan_overlays_source.py tests/test_technical_pipeline_persistence.py tests/test_ai_agent_refactor.py
    } finally { Pop-Location }
}
Invoke-Step "compose-contract" { docker compose config -q }
Invoke-Step "benchmark" { python scripts/benchmark_cad_ingestion.py --corpus $Corpus --output "$ArtifactsDirectory/benchmark.json" }

if ($WithDocker) {
    Invoke-Step "build-backend" { docker compose build backend }
    Invoke-Step "migrate" { docker compose run --rm backend alembic upgrade head }
}

Write-Host "CAD certification completed. Docker migration/build checks require -WithDocker."
