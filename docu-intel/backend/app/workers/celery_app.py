import logging

from celery import Celery
from celery.schedules import schedule
from celery.signals import (
    before_task_publish,
    task_failure,
    task_postrun,
    task_prerun,
    worker_process_init,
)

from app.core.config import settings
from app.services.events_bus import publish_event_sync


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


# --------------------------------------------------------------------- #
# OCR flow event publishing                                              #
# --------------------------------------------------------------------- #
#
# These signals publish lifecycle events to the Redis pub/sub bus so the
# admin UI can show live job activity. We only forward the OCR-flow
# tasks (single-document or batch re-embed / re-OCR) — maintenance
# tasks (scan, learning, webhooks) are excluded to avoid drowning the
# channel in noise. ``publish_event_sync`` swallows every error, so a
# broker hiccup never breaks a worker.

_OCR_FLOW_TASKS: frozenset[str] = frozenset(
    {
        "app.workers.tasks.process_document_task",
        "app.workers.tasks.scan_input_folders_task",  # emits 1 event per detected file
        "app.workers.embedding_tasks.reembed_pending_documents_task",
        "app.workers.embedding_tasks.reprocess_with_new_ocr_engine_task",
        "app.workers.learning_tasks.reclassify_document_task",
    }
)


def _extract_document_id(args: tuple | list | None, kwargs: dict | None) -> int | None:
    """Best-effort extraction of ``document_id`` from a task's positional args.

    All OCR-flow tasks take either ``(document_id, job_id)`` (single
    document) or ``()`` (batch). We only look at the first positional.
    """
    if not args:
        return None
    first = args[0]
    if isinstance(first, int):
        return first
    if isinstance(first, dict):
        value = first.get("document_id")
        if isinstance(value, int):
            return value
    return None


@before_task_publish.connect
def _ocr_flow_on_publish(sender=None, headers=None, body=None, **kwargs) -> None:
    """Emit ``job.queued`` when a producer enqueues a tracked task.

    This fires before the worker has picked the task up, so the live
    UI gets an early "this is about to happen" hint. A subsequent
    ``task_prerun`` (and the persisted ``ExtractionJob`` row) will
    confirm the actual start.
    """
    task_name = (headers or {}).get("task") or sender
    if not task_name or task_name not in _OCR_FLOW_TASKS:
        return
    document_id = None
    if isinstance(body, (list, tuple)) and body:
        document_id = _extract_document_id(body[0], None)
    try:
        publish_event_sync(
            "job.queued",
            {"task": task_name, "document_id": document_id},
        )
    except Exception:  # pragma: no cover - never break a publish
        logger.exception("ocr_flow_on_publish failed for %s", task_name)


@task_prerun.connect
def _ocr_flow_on_prerun(task_id=None, task=None, args=None, kwargs=None, **other) -> None:
    """Emit ``job.started`` when the worker actually starts a tracked task."""
    if not task or task.name not in _OCR_FLOW_TASKS:
        return
    document_id = _extract_document_id(args, kwargs)
    try:
        publish_event_sync(
            "job.started",
            {
                "task": task.name,
                "task_id": task_id,
                "document_id": document_id,
            },
        )
    except Exception:  # pragma: no cover
        logger.exception("ocr_flow_on_prerun failed for %s", getattr(task, "name", "?"))


@task_postrun.connect
def _ocr_flow_on_postrun(
    task=None,
    task_id=None,
    args=None,
    kwargs=None,
    state=None,
    runtime=None,
    **other,
) -> None:
    """Emit ``job.finished`` after a tracked task returns (success or soft-fail)."""
    if not task or task.name not in _OCR_FLOW_TASKS:
        return
    document_id = _extract_document_id(args, kwargs)
    try:
        publish_event_sync(
            "job.finished",
            {
                "task": task.name,
                "task_id": task_id,
                "document_id": document_id,
                "state": state,
                "runtime_s": runtime,
            },
        )
    except Exception:  # pragma: no cover
        logger.exception("ocr_flow_on_postrun failed for %s", getattr(task, "name", "?"))


@task_failure.connect
def _ocr_flow_on_failure(
    task=None,
    task_id=None,
    args=None,
    kwargs=None,
    exception=None,
    **other,
) -> None:
    """Emit ``job.failed`` when a tracked task raises."""
    if not task or task.name not in _OCR_FLOW_TASKS:
        return
    document_id = _extract_document_id(args, kwargs)
    try:
        publish_event_sync(
            "job.failed",
            {
                "task": task.name,
                "task_id": task_id,
                "document_id": document_id,
                "error": str(exception) if exception else None,
            },
        )
    except Exception:  # pragma: no cover
        logger.exception("ocr_flow_on_failure failed for %s", getattr(task, "name", "?"))
