from __future__ import annotations

import logging
import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.database.session import get_db
from app.models import User

router = APIRouter(tags=["health"])

logger = logging.getLogger(__name__)


def _redis_client():
    try:
        from redis import Redis

        return Redis.from_url(settings.redis_url, socket_timeout=2)
    except Exception:
        logger.debug("redis_client_init_failed", exc_info=True)
        return None


@router.get("/db")
def health_db(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        db.execute(text("SELECT 1"))
        return {"database": "ok"}
    except Exception as exc:
        logger.error("health_db_error detail=%s", str(exc))
        return {"database": "error", "detail": "Database connection failed"}


@router.get("/redis")
def health_redis(_: User = Depends(get_current_user)):
    client = _redis_client()
    if client is None:
        return {"redis": "error", "detail": "Redis not configured"}
    try:
        client.ping()
        return {"redis": "ok"}
    except Exception as exc:
        logger.error("health_redis_error detail=%s", str(exc))
        return {"redis": "error", "detail": "Redis connection failed"}


@router.get("/disk")
def health_disk(_: User = Depends(get_current_user)):
    paths = {
        "files_dir": str(settings.files_dir),
        "input_dir": str(settings.input_dir),
    }
    result = {}
    for name, path in paths.items():
        try:
            usage = shutil.disk_usage(str(path))
            free_gb = usage.free / (1024**3)
            result[name] = {
                "path": path,
                "free_gb": round(free_gb, 1),
                "status": "ok" if free_gb > 5 else "warning",
            }
        except Exception as exc:
            logger.error("health_disk_error path=%s detail=%s", path, str(exc))
            result[name] = {"path": path, "status": "error", "detail": "Disk check failed"}
    return result


@router.get("/full")
def health_full(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    checks = {}

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.error("health_full_db_error detail=%s", str(exc))
        checks["database"] = "error"

    client = _redis_client()
    if client is None:
        checks["redis"] = "error"
    else:
        try:
            client.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            logger.error("health_full_redis_error detail=%s", str(exc))
            checks["redis"] = "error"

    overall = all(v == "ok" for v in checks.values())
    return {"status": "healthy" if overall else "degraded", "checks": checks}
