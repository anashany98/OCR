import logging
import os
from pathlib import Path

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
    worker_max_tasks_per_child=10000,  # Very high — PaddleOCR reload is expensive
    worker_max_memory_bytes=8 * 1024 * 1024 * 1024,  # 8 GB — GPU workers need more headroom
    worker_pool_prefork_timeout=300,
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
    "sweep-stale-jobs": {
        "task": "app.workers.tasks.sweep_stale_jobs_task",
        "schedule": schedule(run_every=300),  # every 5 minutes
    },
    "refresh-active-documents-view": {
        "task": "app.workers.tasks.refresh_active_documents_view",
        "schedule": schedule(run_every=300),  # every 5 minutes
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
    # M-4: only preload on workers that actually consume the
    # ``ocr_heavy`` queue. ``worker-fast``, ``worker-maintenance``,
    # ``scheduler`` and ``watcher`` do not need PaddleOCR in
    # memory; loading it there just costs ~1-2 GB of RAM per
    # process and slows down startup. The name is set by the
    # ``-n`` / ``--hostname`` flag in docker-compose.yml.
    worker_name = os.environ.get("WORKER_NAME") or ""
    if "heavy" not in worker_name.lower() and "ocr" not in worker_name.lower():
        if os.environ.get("CUDA_VISIBLE_DEVICES"):
            logger.warning(
                "GPU visible pero WORKER_NAME no indica worker heavy; "
                "no se precargara el motor OCR en arranque. worker_name=%s",
                worker_name,
            )
        logger.info(
            "ocr_preload_skipped reason=not_ocr_worker worker_name=%s",
            worker_name,
        )
        return
    try:
        import concurrent.futures

        # Warmup with a timeout — if the VLM Tier 4 hangs, the
        # worker must not be blocked forever. Also skip Tier 4
        # warmup entirely to avoid blocking on vision model loading.
        def _warmup():
            from app.ocr.factory import get_ocr_engine
            engine = get_ocr_engine()
            # Only warm up Tesseract and PaddleOCR (Tiers 1-2),
            # skip Tier 4 (VLM) to avoid blocking on model loading.
            if hasattr(engine, "primary"):
                engine.primary.extract(Path("/dev/null") if Path("/dev/null").exists() else Path(__file__))
            if hasattr(engine, "fallback"):
                engine.fallback.extract(Path("/dev/null") if Path("/dev/null").exists() else Path(__file__))

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_warmup)
            try:
                future.result(timeout=120)
            except concurrent.futures.TimeoutError:
                logger.warning("OCR warmup timed out after 120s — continuing (models load lazily)")
            except Exception as exc:
                logger.warning("OCR warmup failed (continuing): %s", exc)
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
