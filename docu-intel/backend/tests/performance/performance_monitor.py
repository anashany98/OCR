import time
import log
from functools import wraps
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class PerformanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = time.time() - start

        status = response.status_code
        method = request.method
        path = request.url.path

        log.info(f"{method} {path} {status} {elapsed:.3f}s")

        if elapsed > 1.0:
            log.warning(f"SLOW REQUEST: {method} {path} took {elapsed:.3f}s")

        response.headers["X-Response-Time"] = f"{elapsed:.3f}"
        return response


def timeit(func):
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        log.info(f"{func.__name__} took {elapsed:.3f}s")
        return result

    async def async_wrapper(*args, **kwargs):
        start = time.time()
        result = await func(*args, **kwargs)
        elapsed = time.time() - start
        log.info(f"{func.__name__} took {elapsed:.3f}s")
        return result

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


import asyncio
