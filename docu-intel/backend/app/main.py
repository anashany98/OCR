from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.rate_limit import limiter
from app.database.init_db import create_initial_admin
from app.database.session import SessionLocal
from app.middleware.performance_monitor import PerformanceMonitorMiddleware
from app.services.metrics import register_metrics_endpoint


setup_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    db = SessionLocal()
    try:
        create_initial_admin(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Rate limiting must be added before other middleware
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Performance monitoring
app.add_middleware(PerformanceMonitorMiddleware)

# CORS configuration - more restrictive in production
allow_origins = settings.cors_origins
if settings.environment == "production":
    # In production, ensure only specific domains are allowed
    allow_origins = [origin.strip() for origin in allow_origins if origin.strip() and not origin.startswith("http://localhost")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-DocuIntel-API-Key", "X-Technician-Id", "X-Technician-Name"],
    max_age=600,  # Cache preflight requests for 10 minutes
)

app.include_router(api_router, prefix=settings.api_v1_prefix)

# Register Prometheus metrics endpoint
register_metrics_endpoint(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
