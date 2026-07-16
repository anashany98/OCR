from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    import redis
except ModuleNotFoundError:  # pragma: no cover - exercised in lightweight local test environments
    redis = None


class CacheService:
    def __init__(self):
        self._client: Any | None = None
        self._unavailable_until = 0.0

    def _available(self) -> bool:
        return time.monotonic() >= self._unavailable_until

    def _mark_unavailable(self) -> None:
        self._unavailable_until = time.monotonic() + 30.0

    @property
    def client(self) -> Any:
        if redis is None:
            raise RuntimeError("redis package is not installed")
        if self._client is None:
            pool = redis.ConnectionPool.from_url(
                settings.redis_url,
                max_connections=20,
                decode_responses=True,
                # Cache is best-effort.  A missing Redis must not make an
                # ingestion poll (or its unit tests) wait for DNS/TCP retry
                # defaults on every file.
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
            )
            self._client = redis.Redis(connection_pool=pool)
        return self._client

    def get(self, key: str) -> Any | None:
        if not self._available():
            return None
        try:
            data = self.client.get(key)
            if data is None:
                return None
            return json.loads(data)
        except Exception:
            self._mark_unavailable()
            logger.debug("cache_get_failed key=%s", key, exc_info=True)
            return None

    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> bool:
        if not self._available():
            return False
        try:
            self.client.setex(key, ttl_seconds, json.dumps(value))
            return True
        except Exception:
            self._mark_unavailable()
            logger.debug("cache_set_failed key=%s", key, exc_info=True)
            return False

    def delete(self, key: str) -> bool:
        if not self._available():
            return False
        try:
            self.client.delete(key)
            return True
        except Exception:
            self._mark_unavailable()
            logger.debug("cache_delete_failed key=%s", key, exc_info=True)
            return False

    def delete_pattern(self, pattern: str) -> int:
        if not self._available():
            return 0
        try:
            deleted = 0
            batch: list[str] = []
            for key in self.client.scan_iter(match=pattern, count=500):
                batch.append(key)
                if len(batch) >= 500:
                    deleted += self.client.delete(*batch)
                    batch.clear()
            if batch:
                deleted += self.client.delete(*batch)
            return deleted
        except Exception:
            self._mark_unavailable()
            logger.debug("cache_delete_pattern_failed pattern=%s", pattern, exc_info=True)
            return 0

    def invalidate_search_cache(self) -> int:
        return self.delete_pattern("search:*")


cache_service = CacheService()
