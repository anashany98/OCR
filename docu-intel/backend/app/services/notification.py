from __future__ import annotations


import redis

from app.core.config import settings


class NotificationService:
    def __init__(self):
        self._redis_client: redis.Redis | None = None

    @property
    def redis(self) -> redis.Redis:
        if self._redis_client is None:
            self._redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis_client

    def notify_job_failed(self, job_id: int, document_id: int, error: str) -> bool:
        try:
            self.redis.publish(
                "notifications",
                __import__("json").dumps(
                    {
                        "type": "job_failed",
                        "job_id": job_id,
                        "document_id": document_id,
                        "error": error[:500],
                        "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
                    }
                ),
            )
            return True
        except Exception:
            return False

    def notify_document_processed(self, document_id: int, filename: str) -> bool:
        try:
            self.redis.publish(
                "notifications",
                __import__("json").dumps(
                    {
                        "type": "document_processed",
                        "document_id": document_id,
                        "filename": filename,
                        "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
                    }
                ),
            )
            return True
        except Exception:
            return False


notification_service = NotificationService()
