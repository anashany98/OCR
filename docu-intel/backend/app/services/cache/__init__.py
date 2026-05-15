from __future__ import annotations

import json
from typing import Any

from app.core.config import settings

try:
    import redis
except ModuleNotFoundError:  # pragma: no cover - exercised in lightweight local test environments
    redis = None


class CacheService:
    def __init__(self):
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if redis is None:
            raise RuntimeError("redis package is not installed")
        if self._client is None:
            self._client = redis.from_url(settings.redis_url, decode_responses=True)
        return self._client

    def get(self, key: str) -> Any | None:
        try:
            data = self.client.get(key)
            if data is None:
                return None
            return json.loads(data)
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> bool:
        try:
            self.client.setex(key, ttl_seconds, json.dumps(value))
            return True
        except Exception:
            return False

    def delete(self, key: str) -> bool:
        try:
            self.client.delete(key)
            return True
        except Exception:
            return False

    def delete_pattern(self, pattern: str) -> int:
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
            return 0

    def invalidate_search_cache(self) -> int:
        return self.delete_pattern("search:*")


cache_service = CacheService()
