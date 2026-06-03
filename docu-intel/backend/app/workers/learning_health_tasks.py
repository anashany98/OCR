"""Celery tasks that maintain the health of the learning loop."""
from __future__ import annotations

import logging

from app.database.session import SessionLocal
from app.services import learning_health
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.learning_health_tasks.auto_reject_stale_suggestions_task")
def auto_reject_stale_suggestions_task() -> dict:
    """Mark and auto-reject stale classification_suggestions.

    Runs daily via Celery Beat on the maintenance queue. Can also be triggered
    manually from the admin UI for an immediate clean-up.
    """
    db = SessionLocal()
    try:
        marked = learning_health.mark_stale_suggestions(db)
        result = learning_health.auto_reject_stale_suggestions(db)
        logger.info(
            "learning_health_auto_reject marked=%s rejected=%s remaining=%s",
            marked,
            result["rejected"],
            result["remaining"],
        )
        return {"marked_stale": marked, **result}
    finally:
        db.close()
