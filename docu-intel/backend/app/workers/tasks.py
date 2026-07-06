import logging
from datetime import datetime, timezone

from celery.exceptions import Reject
from sqlalchemy import select

from app.database.session import SessionLocal
from app.ingestion.scanner import scan_input_folders
from app.models import ExtractionJob
from app.services.document_service import process_document
from app.workers.celery_app import celery_app
from app.workers.errors import (
    RETRYABLE_EXCEPTIONS,
    is_permanent,
    mark_job_as_failed,
    notify_failed,
)

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.tasks.process_document_task",
    bind=True,
    autoretry_for=RETRYABLE_EXCEPTIONS,  # WRK-RETRY-1: narrow allow-list
    retry_backoff=True,
    retry_backoff_max=300,  # cap the exponential backoff at 5 min
    retry_jitter=True,  # avoid thundering herd on retry
    max_retries=3,
    soft_time_limit=900,  # 15 min soft kill (SIGTERM, can clean up)
    time_limit=1200,  # 20 min hard kill (SIGKILL)
    acks_late=True,  # ack only after work is done
)
def process_document_task(self, document_id: int, job_id: int) -> None:
    """Process a single document.

    Retry policy (WRK-RETRY-1):

    * **Transient errors** (``OperationalError``, ``ConnectionError``,
      ``socket.timeout``, etc. — see
      :data:`app.workers.errors.RETRYABLE_EXCEPTIONS`): Celery
      re-queues with exponential backoff (max 5 min, jittered).
      After ``max_retries=3`` attempts the message is moved to
      Celery's dead-letter.
    * **Permanent errors** (``FileNotFoundError``,
      ``PermissionError``, ``IntegrityError``, ``DataError``,
      ``ValueError``, …): the task marks the job as ``failed`` and
      ``Reject``-s the message so the worker does not pick it up
      again. The admin UI sees the failure immediately.
    """
    db = SessionLocal()
    try:
        job = db.get(ExtractionJob, job_id)
        if job and hasattr(job, "retries"):
            job.retries = int(getattr(self.request, "retries", 0) or 0)
            db.commit()
        final_failure = int(getattr(self.request, "retries", 0) or 0) >= int(
            getattr(self, "max_retries", 0) or 0
        )
        try:
            process_document(
                db, document_id=document_id, job_id=job_id, final_failure=final_failure
            )
        except Exception as exc:
            # Refresh the job in case the inner function detached
            # it from the session.
            db.expire_all()
            job = db.get(ExtractionJob, job_id)
            if is_permanent(exc):
                # Non-retryable: mark the job as failed now, notify,
                # and Reject the message so it does not come back.
                # We do this BEFORE re-raising so the admin sees
                # the failure even if the worker dies between the
                # raise and the ack.
                mark_job_as_failed(db, job, exc)
                db.commit()
                notify_failed(
                    job_id=job_id,
                    document_id=document_id,
                    exc=exc,
                )
                raise Reject(exc, requeue=False) from exc
            # Retryable: log + re-raise so Celery's autoretry_for
            # kicks in. We do NOT mark the job as failed here; the
            # final attempt (after max_retries) is what triggers
            # the failed status. The job row is updated at
            # final_failure=True time by ``process_document``.
            raise
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.scan_input_folders_task")
def scan_input_folders_task() -> dict:
    """Periodic scan of the input folders.

    No time limit / no autoretry: a stuck scan is recovered by
    the periodic rescan inside ``run_watch_loop`` (the watcher's
    own watchdog) and by the next Beat tick. A short
    ``soft_time_limit`` would be too aggressive given the scan
    walks up to ``WATCHER_MAX_FILES_PER_TICK`` files.
    """
    db = SessionLocal()
    try:
        return scan_input_folders(db, user=None, enqueue=True)
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.sweep_stale_jobs_task")
def sweep_stale_jobs_task() -> dict:
    """Reset extraction jobs stuck in 'processing' for >30 minutes.

    A worker killed mid-processing (between Celery ack and db.commit)
    leaves the job in 'processing' permanently. This beat task sweeps
    them every 5 minutes so the document can be re-queued.
    """
    from datetime import timedelta

    from sqlalchemy import and_

    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        stale = db.scalars(
            select(ExtractionJob).where(
                and_(
                    ExtractionJob.status == "processing",
                    ExtractionJob.started_at < cutoff,
                )
            )
        ).all()
        reset_count = 0
        for job in stale:
            job.status = "failed"
            job.error_message = "Worker died mid-processing (sweeper timeout)"
            job.finished_at = datetime.now(timezone.utc)
            reset_count += 1
        if reset_count:
            db.commit()
            logger.warning("Sweeper reset %d stale processing jobs", reset_count)
            from app.services.metrics.pipeline import track_stale_jobs_reset
            track_stale_jobs_reset(reset_count)
        return {"stale_reset": reset_count}
    except Exception as exc:
        db.rollback()
        logger.error("Stale job sweeper failed: %s", exc)
        return {"stale_reset": 0, "error": str(exc)}
    finally:
        db.close()


@celery_app.task(
    name="app.workers.tasks.refresh_active_documents_view",
    queue="maintenance",
)
def refresh_active_documents_view() -> dict:
    """Refresh the mv_active_documents materialized view.

    Runs periodically (every 5 min via Celery beat) so the document
    list endpoint can query the small materialized view instead of
    filtering the full documents table each time.
    """
    db = SessionLocal()
    try:
        db.execute(
            __import__("sqlalchemy").text(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_active_documents"
            )
        )
        db.commit()
        logger.info("Refreshed mv_active_documents materialized view")
        return {"status": "ok"}
    except Exception as exc:
        db.rollback()
        logger.warning("Failed to refresh mv_active_documents: %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        db.close()
