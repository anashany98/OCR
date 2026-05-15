from celery import Celery
from celery.schedules import schedule

from app.core.config import settings

celery_app = Celery(
    "docuintel",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Madrid",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_default_queue="text_fast",
    task_routes={
        "app.workers.tasks.process_document_task": {"queue": "text_fast"},
        "app.workers.tasks.scan_input_folders_task": {"queue": "maintenance"},
    },
)
celery_app.conf.beat_schedule = {
    "scan-input-folders": {
        "task": "app.workers.tasks.scan_input_folders_task",
        "schedule": schedule(run_every=settings.scan_interval_seconds),
    }
}
