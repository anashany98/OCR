import logging

from celery import Celery
from celery.schedules import schedule
from celery.signals import worker_process_init

from app.core.config import settings


logger = logging.getLogger("app.workers.celery_app")

celery_app = Celery(
    "docuintel",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.tasks",
        "app.workers.learning_tasks",
        "app.workers.learning_health_tasks",
        "app.workers.webhooks_tasks",
        "app.workers.embedding_tasks",
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
    "reembed-pending-documents": {
        "task": "app.workers.embedding_tasks.reembed_pending_documents_task",
        "schedule": schedule(run_every=settings.reembed_interval_seconds),
    },
}
celery_app.conf.task_routes = {
    **celery_app.conf.task_routes,
    "app.workers.learning_tasks.process_approved_suggestions_task": {"queue": "maintenance"},
    "app.workers.learning_tasks.reclassify_document_task": {"queue": "maintenance"},
    "app.workers.learning_health_tasks.auto_reject_stale_suggestions_task": {
        "queue": "maintenance"
    },
    "app.workers.webhooks_tasks.deliver_pending_webhooks_task": {"queue": "maintenance"},
    "app.workers.embedding_tasks.reembed_pending_documents_task": {"queue": "maintenance"},
}


@worker_process_init.connect
def preload_worker_ocr_engine(**_kwargs) -> None:
    """Preload the OCR engine + force a synthetic compile pass.

    OCR-INIT-1 (Sprint 2): the previous implementation only
    triggered the lazy ``cached_property`` that loads the model
    weights. Paddle and Tesseract both do *additional* one-time
    work on the first real call (Paddle compiles the inference
    graph for the actual image dimensions, Tesseract allocates
    its working memory). The new :func:`preload_ocr_engine`
    helper runs a synthetic-image extraction so those costs are
    paid during worker boot, not during the first real job.

    Failures are no longer silenced: a missing Paddle install
    or a broken model download is logged with ``logger.exception``
    (stack trace included) and emitted as a Prometheus counter
    so the operator can dashboard it.
    """
    try:
        from app.ocr.factory import preload_ocr_engine

        preload_ocr_engine()
    except Exception:
        # OCR-INIT-1: preserve the full stack trace (no more
        # ``logger.warning(exc)`` swallowing the chain) and emit
        # a metric so the failure is visible in the operator
        # dashboard.
        logger.exception("OCR engine preload failed during worker init")
        try:
            from app.services.metrics import track_worker_init_failure

            track_worker_init_failure(stage="ocr_preload")
        except Exception:  # pragma: no cover - never let metrics break the worker boot
            logger.exception("worker_init_failure_metric_emission_failed")
