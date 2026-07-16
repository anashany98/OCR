[CmdletBinding()]
param(
    [switch]$Resume,
    [switch]$SkipFrontend,
    [switch]$SkipDocker,
    [switch]$RunLiveM3,
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
    # Keep the runner compatible with Windows PowerShell 5.1 as well as
    # PowerShell 7: ``ConvertFrom-Json -AsHashtable`` only exists in PS 6+.
    $Previous = Get-Content -Raw -Path $StatePath | ConvertFrom-Json
    $State = @{
        run_id = [string]$Previous.run_id
        started_at = [string]$Previous.started_at
        stages = @{}
    }
    foreach ($Property in $Previous.stages.PSObject.Properties) {
        $State.stages[$Property.Name] = @{
            status = [string]$Property.Value.status
            log = [string]$Property.Value.log
        }
    }
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
    Invoke-External "docker" $Arguments
}

function Invoke-External {
    param(
        [Parameter(Mandatory)][string]$File,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    # Windows PowerShell 5.1 turns native stderr into a terminating error
    # under ``ErrorActionPreference=Stop`` even when the process exited 0.
    # Preserve the process exit code as the contract instead.
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $File @Arguments
        $ExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($ExitCode -ne 0) {
        # Do not echo arguments here: DATABASE_URL can contain a password.
        throw "$File exited with $ExitCode"
    }
}

function Get-ComposePostgresPassword {
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $Value = & docker compose exec -T postgres sh -lc 'printf %s "$POSTGRES_PASSWORD"'
        $ExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($Value)) {
        throw "Could not read the configured PostgreSQL password from the compose service."
    }
    return ([string]$Value).Trim()
}

function Get-ComposeBackendEnvironmentValue {
    param([Parameter(Mandatory)][string]$Name)
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $Value = & docker compose exec -T backend sh -lc "printenv $Name"
        $ExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($Value)) {
        throw "Could not read backend environment variable $Name."
    }
    return ([string]$Value).Trim()
}

function Start-TemporaryRedis {
    param([Parameter(Mandatory)][string]$Name)

    # The host-side Python suite cannot resolve Compose's internal ``redis``
    # hostname.  Run an isolated Redis on a Docker-assigned loopback port so
    # cache-isolation tests exercise a real server without exposing or
    # modifying the development Compose service.
    # Do not use ``Invoke-External`` here. Native stdout from ``docker run``
    # is the container id and PowerShell can capture it together with the
    # return value of this function, corrupting REDIS_URL as
    # "<container-id> redis://...". Capture it explicitly and expose only the
    # constructed URL below.
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $ContainerId = & docker run -d --rm --name $Name -p "127.0.0.1::6379" redis:7-alpine
        $RunExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($RunExitCode -ne 0 -or [string]::IsNullOrWhiteSpace(([string]$ContainerId).Trim())) {
        throw "Could not start temporary Redis container $Name."
    }
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $PreviousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $Mapping = [string](& docker port $Name "6379/tcp")
            $InspectExitCode = $LASTEXITCODE
            $Ping = (& docker exec $Name redis-cli ping).Trim()
            $PingExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $PreviousErrorActionPreference
        }
        $PortMatch = [regex]::Match($Mapping, ':(\d+)\s*$')
        $Port = if ($PortMatch.Success) { $PortMatch.Groups[1].Value } else { "" }
        if ($InspectExitCode -eq 0 -and $PingExitCode -eq 0 -and $Port -match '^\d+$' -and $Ping -eq "PONG") {
            return "redis://127.0.0.1:$Port/15"
        }
        Start-Sleep -Seconds 1
    }
    throw "Temporary Redis $Name did not become ready."
}

function Stop-TemporaryRedis {
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($Name)) {
        return
    }
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & docker rm -f $Name | Out-Null
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
}

Invoke-CertificationStage "baseline" {
    Invoke-External "git" @("diff", "--check")
    Invoke-External "python" @("-m", "compileall", "-q", "backend/app")
    Push-Location backend
    try {
        Invoke-External "python" @("-m", "pytest", "-q", "tests/test_project_path_resolver.py", "tests/test_classification.py", "tests/test_mass_ingestion.py")
    } finally {
        Pop-Location
    }
}

Invoke-CertificationStage "tenant-isolation" {
    Push-Location backend
    try {
        Invoke-External "python" @("-m", "pytest", "-q", "tests/test_tenant_deny_by_default.py", "tests/test_tenant_deny_by_default_exhaustive.py", "tests/test_tenant_access.py")
    } finally {
        Pop-Location
    }
}

$TemporaryRedisName = ("$($State.run_id -replace '[^a-zA-Z0-9-]', '-')-cache").ToLowerInvariant()
if ($TemporaryRedisName -notmatch '^terra-cert-[a-z0-9-]+-cache$') {
    throw "Refusing to use unsafe temporary Redis container name: $TemporaryRedisName"
}
$TemporaryRedisUrl = $null
try {
    $TemporaryRedisUrl = Start-TemporaryRedis $TemporaryRedisName
    Invoke-CertificationStage "backend-suite" {
        $PreviousRedisUrl = $env:REDIS_URL
        $PreviousM3Enabled = $env:M3_TEST_ENABLED
        $PreviousM3AdminUser = $env:M3_TEST_ADMIN_USER
        $PreviousM3AdminPass = $env:M3_TEST_ADMIN_PASS
        try {
            $env:REDIS_URL = $TemporaryRedisUrl
            if ($RunLiveM3) {
                if ([string]::IsNullOrWhiteSpace($env:M3_TEST_VIEWER_USER) -or [string]::IsNullOrWhiteSpace($env:M3_TEST_VIEWER_PASS)) {
                    throw "-RunLiveM3 requires M3_TEST_VIEWER_USER and M3_TEST_VIEWER_PASS for a scoped non-admin account."
                }
                $env:M3_TEST_ENABLED = "1"
                $env:M3_TEST_ADMIN_USER = Get-ComposeBackendEnvironmentValue "ADMIN_EMAIL"
                $env:M3_TEST_ADMIN_PASS = Get-ComposeBackendEnvironmentValue "ADMIN_PASSWORD"
            } else {
                $env:M3_TEST_ENABLED = "0"
            }
            Push-Location backend
            try {
                Invoke-External "python" @("-m", "pytest", "-q", "tests")
            } finally {
                Pop-Location
            }
        } finally {
            if ($null -eq $PreviousRedisUrl) {
                Remove-Item Env:REDIS_URL -ErrorAction SilentlyContinue
            } else {
                $env:REDIS_URL = $PreviousRedisUrl
            }
            foreach ($entry in @(
                @{ Name = "M3_TEST_ENABLED"; Value = $PreviousM3Enabled },
                @{ Name = "M3_TEST_ADMIN_USER"; Value = $PreviousM3AdminUser },
                @{ Name = "M3_TEST_ADMIN_PASS"; Value = $PreviousM3AdminPass }
            )) {
                if ($null -eq $entry.Value) {
                    Remove-Item "Env:$($entry.Name)" -ErrorAction SilentlyContinue
                } else {
                    Set-Item "Env:$($entry.Name)" $entry.Value
                }
            }
        }
    }
} finally {
    Stop-TemporaryRedis $TemporaryRedisName
}

if (-not $SkipFrontend) {
    Invoke-CertificationStage "frontend-build" { Invoke-External "npm" @("--prefix", "frontend", "run", "build") }
    Invoke-CertificationStage "frontend-tests" { Invoke-External "npm" @("--prefix", "frontend", "run", "test") }
}

if (-not $SkipDocker) {
    $TemporaryDatabase = ("$($State.run_id -replace '[^a-zA-Z0-9_]', '_')").ToLowerInvariant()
    if ($TemporaryDatabase -notmatch '^terra_cert_[a-z0-9_]+$') {
        throw "Refusing to use unsafe temporary database name: $TemporaryDatabase"
    }
    # Compose may load a non-default password from .env; use the value from
    # the already-running service rather than assuming the development default.
    $Password = Get-ComposePostgresPassword
    $TemporaryDatabaseUrl = "postgresql+psycopg://app:$Password@postgres:5432/$TemporaryDatabase"

    # A failed run always drops its temporary database in ``finally``.  These
    # stages therefore cannot be resumed as "passed" even when a prior
    # attempt reached database creation before failing migrations.
    foreach ($StageName in @("postgres-create", "postgres-migrations", "postgres-e2e", "docker-health")) {
        if ($State.stages.ContainsKey($StageName)) {
            $State.stages.Remove($StageName)
        }
    }
    Save-State

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
            Invoke-Docker @("compose", "run", "--rm", "--no-deps", "--entrypoint", "sh", "-v", $mount, "-w", "/workspace", "-e", "DATABASE_URL=$TemporaryDatabaseUrl", "backend", "-lc", "${slow}EMBEDDING_PROVIDER=local_hash EMBEDDING_DIMENSIONS=768 python -m pytest -q tests/test_terra_project_lifecycle_e2e.py tests/test_ocr_cascade.py tests/test_ocr_engine_tracking.py tests/test_ocr_golden.py tests/test_ocr_init_warmup.py tests/test_ocr_language.py tests/test_ocr_paddle.py tests/test_ocr_postprocess.py tests/test_ocr_preprocess.py tests/test_ocr_review.py -p no:cacheprovider")
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
