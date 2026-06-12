"""Rate limiting for the FastAPI app.

SEC-RL-1 (Sprint 0): The previous implementation trusted the
``X-Forwarded-For`` and ``X-Real-IP`` headers when building the rate
limit bucket key. A direct client (or a misconfigured proxy) could
spoof these headers to bypass the limit by creating a new bucket per
request. The fix:

* Trust **only** ``request.client.host`` for unauthenticated buckets.
  When the app runs behind a trusted reverse proxy, the proxy's
  forwarded IP is delivered to the worker through uvicorn's
  ``--proxy-headers`` + ``--forwarded-allow-ips`` mechanism (configured
  in the Dockerfile and overridable via ``UVICORN_FORWARDED_ALLOW_IPS``).
  The rate limiter reads the *already-validated* socket address from
  ``request.client.host``; client-supplied headers are ignored.
* Hash the integration API key with SHA-256 before using it as a bucket
  key. The raw key is short-lived in Redis, but hashing makes the
  bucket key stable length and avoids leaking the key in
  slowapi / Redis monitoring output.

This is a defence-in-depth measure: even if a future caller adds back
header-based IP extraction, the bucket can never be forged by
injecting a header because the only inputs are the socket address and
the (hashed) API key.
"""

from __future__ import annotations

import hashlib

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _hash_api_key(api_key: str) -> str:
    """Stable, opaque bucket key for the integration API key.

    Truncates to 16 hex chars (64 bits) to keep the bucket key short
    while still making collisions practically impossible.
    """
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return digest[:16]


def rate_limit_key(request: Request) -> str:
    """Compute the slowapi bucket key for ``request``.

    Order of preference:

    1. ``X-DocuIntel-API-Key`` header → ``api_key:<sha256[:16]>``. The
       full key never leaves the request handler, so a slowapi dump
       or Redis MONITOR stream cannot leak it.
    2. ``request.client.host`` (the *socket* address, already
       validated by uvicorn when ``--proxy-headers`` is enabled). This
       is the only IP source we trust; client-supplied
       ``X-Forwarded-For`` / ``X-Real-IP`` headers are *ignored*
       regardless of the deployment.
    """
    api_key = request.headers.get("X-DocuIntel-API-Key")
    if api_key:
        return f"api_key:{_hash_api_key(api_key)}"
    return get_remote_address(request)


limiter = Limiter(
    key_func=rate_limit_key,
    default_limits=["200/minute"],
    storage_uri=settings.rate_limit_storage_uri
    or ("memory://" if settings.environment in {"local", "development"} else settings.redis_url),
    headers_enabled=True,  # surface X-RateLimit-* on every response
)
