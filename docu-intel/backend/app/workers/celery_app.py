from celery import Celery
from celery.schedules import schedule

from app.core.config import settings

celery_app = Celery(
    "docuintel",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.tasks",
        "app.workers.learning_tasks",
        "app.workers.learning_health_tasks",
        "app.workers.webhooks_tasks",
    ],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Madrid",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_acks_late=True,
    task_default_queue="text_fast",
    task_routes={
        "app.workers.tasks.scan_input_folders_task": {"queue": "maintenance"},
    },
)
celery_app.conf.beat_schedule = {
    "scan-input-folders": {
        "task": "app.workers.tasks.scan_input_folders_task",
        "schedule": schedule(run_every=settings.scan_interval_seconds),
    },
    "process-approved-suggestions": {
        "task": "app.workers.learning_tasks.process_approved_suggestions_task",
        "schedule": schedule(run_every=settings.learning_interval_seconds),
    },
    "deliver-pending-webhooks": {
        "task": "app.workers.webhooks_tasks.deliver_pending_webhooks_task",
        "schedule": schedule(run_every=settings.webhook_outbox_interval_seconds),
    },
    "auto-reject-stale-suggestions": {
        "task": "app.workers.learning_health_tasks.auto_reject_stale_suggestions_task",
        "schedule": schedule(run_every=settings.learning_stale_check_interval_seconds),
    },
}
celery_app.conf.task_routes = {
    **celery_app.conf.task_routes,
    "app.workers.learning_tasks.process_approved_suggestions_task": {"queue": "maintenance"},
    "app.workers.learning_tasks.reclassify_document_task": {"queue": "maintenance"},
    "app.workers.learning_health_tasks.auto_reject_stale_suggestions_task": {"queue": "maintenance"},
    "app.workers.webhooks_tasks.deliver_pending_webhooks_task": {"queue": "maintenance"},
}
