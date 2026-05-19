from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def rate_limit_key(request: Request) -> str:
    api_key = request.headers.get("X-DocuIntel-API-Key")
    if api_key:
        return f"api_key:{api_key}"
    return get_remote_address(request)


limiter = Limiter(
    key_func=rate_limit_key,
    default_limits=["200/minute"],
    storage_uri=settings.rate_limit_storage_uri
    or ("memory://" if settings.environment in {"local", "development"} else settings.redis_url),
)
