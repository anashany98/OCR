[CmdletBinding()]
param(
    [switch]$WithDocker,
    [string]$Manifest = "artifacts/ovisocr2/corpus.json",
    [string]$ArtifactsDirectory = "artifacts/ovisocr2"
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
Invoke-Step "lint" { python -m ruff check backend/app services/ovisocr2 }
Invoke-Step "format" { python -m ruff format --check backend/app services/ovisocr2 }
Invoke-Step "compile" { python -m compileall -q backend/app services/ovisocr2 }
Invoke-Step "unit-contract" {
    Push-Location backend
    try {
        python -m pytest -q tests/test_ovisocr2_client.py tests/test_ovisocr2_output.py tests/test_ovisocr2_contract.py tests/test_ovisocr2_routing.py tests/test_ovisocr2_cascade.py tests/test_ovisocr2_factory.py tests/test_ovisocr2_golden.py tests/test_ovisocr2_integration.py
    } finally { Pop-Location }
}
Invoke-Step "compose-contract" { docker compose --profile ovisocr2 config -q }

if ($WithDocker) {
    Invoke-Step "build" { docker compose --profile ovisocr2 build ovisocr2 }
    Invoke-Step "start" { docker compose --profile ovisocr2 up -d ovisocr2 }
    Invoke-Step "ready" {
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            docker compose --profile ovisocr2 exec -T ovisocr2 python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz').read()"
            if ($LASTEXITCODE -eq 0) { return }
            Start-Sleep -Seconds 5
        }
        throw "OvisOCR2 did not become ready within five minutes"
    }
    if (Test-Path $Manifest) {
        Invoke-Step "benchmark" { python scripts/benchmark_ovisocr2.py --manifest $Manifest --output "$ArtifactsDirectory/candidate.json" }
    } else {
        Write-Warning "No corpus manifest at $Manifest; GPU benchmark intentionally not run."
    }
}

Write-Host "OvisOCR2 certification completed. Docker/GPU checks require -WithDocker."
