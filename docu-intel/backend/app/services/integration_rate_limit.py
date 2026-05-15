from __future__ import annotations

from fastapi import HTTPException, status

from app.core.config import settings
from app.services.cache import cache_service


def enforce_integration_rate_limit(*, client_id: int, technician_id: str) -> None:
    limit = int(settings.integration_rate_limit_per_minute or 0)
    if limit <= 0:
        return
    key = f"rate_limit:integration:{client_id}:{technician_id}"
    try:
        count = int(cache_service.client.incr(key))
        if count == 1:
            cache_service.client.expire(key, 60)
    except Exception:
        return
    if count > limit:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Integration rate limit exceeded")
