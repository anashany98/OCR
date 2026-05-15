from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("app.performance")


class PerformanceMonitorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started_at = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started_at

        response.headers["X-Response-Time"] = f"{elapsed:.3f}"
        if elapsed >= 1.0:
            logger.warning(
                "slow_request method=%s path=%s status=%s elapsed=%.3fs",
                request.method,
                request.url.path,
                response.status_code,
                elapsed,
            )
        else:
            logger.debug(
                "request method=%s path=%s status=%s elapsed=%.3fs",
                request.method,
                request.url.path,
                response.status_code,
                elapsed,
            )
        return response
