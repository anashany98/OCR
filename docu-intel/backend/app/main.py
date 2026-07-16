import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.multipart_limits import _APPLIED_MAX_FILES
from app.core.rate_limit import limiter
from app.core.sentry import init_sentry
from app.database.init_db import create_initial_admin
from app.database.session import SessionLocal
from app.middleware.performance_monitor import PerformanceMonitorMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.services.metrics import register_metrics_endpoint

setup_logging()
init_sentry()

# Multipart file-part cap: imported for its side effect (patches
# Starlette's Request._get_form default). Must run before any route
# resolves its dependencies, hence the top-level import.
import logging as _logging  # noqa: E402  (intentional — runs after setup_logging)

_logging.getLogger("app.bootstrap").info(
    "multipart max_files patched from %d to %d",
    1000,
    _APPLIED_MAX_FILES,
)

# H-5: refuse to boot in non-local environments with a permissive
# UVICORN_FORWARDED_ALLOW_IPS. The previous default (``*``) made every
# IP-based rate limit and audit entry spoofable via X-Forwarded-For.
if settings.environment != "local":
    forwarded_allow = os.environ.get("UVICORN_FORWARDED_ALLOW_IPS", "")
    if forwarded_allow.strip() in {"", "*"}:
        raise RuntimeError(
            "UVICORN_FORWARDED_ALLOW_IPS must be set to the reverse-proxy CIDR "
            "(e.g. '10.0.0.5' or '10.0.0.0/8') in non-local environments. "
            "Refusing to boot with '*' or empty (H-5)."
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    # F7-01: migration gate — verify DB schema is current before accepting requests
    _check_migration_head()
    db = SessionLocal()
    try:
        create_initial_admin(db)
    finally:
        db.close()
    yield


def _check_migration_head() -> None:
    """Verify the database schema matches the latest Alembic migration.

    F7-01: refuse to start if migrations are pending. This prevents
    the app from running against a stale schema which would cause
    cryptic runtime errors.
    """
    import logging

    logger = logging.getLogger("app.startup")
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config("alembic.ini")
        script = ScriptDirectory.from_config(config)
        head = script.get_current_head()

        from sqlalchemy import text

        db = SessionLocal()
        try:
            result = db.execute(
                text("SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1")
            )
            row = result.fetchone()
            current = row[0] if row else None
        finally:
            db.close()

        if current != head:
            logger.error(
                "Migration gate: DB schema '%s' does not match Alembic head '%s'. "
                "Run 'alembic upgrade head' before starting the application.",
                current,
                head,
            )
            raise RuntimeError(
                f"Database schema '{current}' does not match Alembic head '{head}'. "
                "Run 'alembic upgrade head' before starting the application."
            )
        logger.info("Migration gate: DB schema '%s' matches Alembic head.", current)
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("Migration gate check failed (continuing): %s", exc)


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Rate limiting must be added before other middleware
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Request ID tracing — must be first so downstream middleware/loggers have access
app.add_middleware(RequestIDMiddleware)

# Performance monitoring
app.add_middleware(PerformanceMonitorMiddleware)

# Security headers
app.add_middleware(SecurityHeadersMiddleware)

# CORS configuration - more restrictive in production
allow_origins = settings.cors_origins
if settings.environment == "production":
    # In production, ensure only specific domains are allowed
    allow_origins = [
        origin.strip()
        for origin in allow_origins
        if origin.strip() and not origin.startswith("http://localhost")
    ]
    if "*" in allow_origins:
        raise ValueError("CORS_ORIGINS must not contain '*' in production environment")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-DocuIntel-API-Key",
        "X-Technician-Id",
        "X-Technician-Name",
    ],
    max_age=600,  # Cache preflight requests for 10 minutes
)

app.include_router(api_router, prefix=settings.api_v1_prefix)

# Register Prometheus metrics endpoint
register_metrics_endpoint(app)

from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.errors import DomainError
import structlog as _structlog

_err_logger = _structlog.get_logger("app.errors")


@app.exception_handler(DomainError)
async def _domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    rid = getattr(request.state, "request_id", "-")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "request_id": rid})


@app.exception_handler(Exception)
async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    rid = getattr(request.state, "request_id", "-")
    _err_logger.exception("unhandled_error", request_id=rid, error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "internal error", "request_id": rid})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/healthz")
def healthz() -> dict[str, str | dict[str, str]]:
    """Readiness real: DB + Redis."""
    from sqlalchemy import text as _sa_text

    checks: dict[str, str] = {}
    try:
        db = SessionLocal()
        try:
            db.execute(_sa_text("SELECT 1"))
            checks["db"] = "ok"
        finally:
            db.close()
    except Exception:
        checks["db"] = "error"
    try:
        import redis as _redis  # type: ignore

        _redis.from_url(settings.redis_url).ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"
    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}
