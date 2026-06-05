from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def rate_limit_key(request: Request) -> str:
    api_key = request.headers.get("X-DocuIntel-API-Key")
    if api_key:
        return f"api_key:{api_key}"
    # Respect reverse-proxy headers for real client IP
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    return get_remote_address(request)


limiter = Limiter(
    key_func=rate_limit_key,
    default_limits=["200/minute"],
    storage_uri=settings.rate_limit_storage_uri
    or ("memory://" if settings.environment in {"local", "development"} else settings.redis_url),
)
