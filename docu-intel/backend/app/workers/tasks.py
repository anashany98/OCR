import logging
from datetime import UTC, datetime

from celery.exceptions import Reject
from sqlalchemy import select

from app.core.config import settings
from app.database.session import SessionLocal
from app.ingestion.scanner import scan_input_folders
from app.models import Document, ExtractionJob
from app.services.document_service import process_document
from app.workers.celery_app import celery_app
from app.workers.errors import (
    RETRYABLE_EXCEPTIONS,
    is_permanent,
    mark_job_as_failed,
    notify_failed,
    truncate_error,
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
                # BUGFIX: mark the DOCUMENT as failed too. Previously only the
                # job was updated, so the document stayed in "processing"
                # forever (no sweeper touched it, since its job was already
                # "failed"). This orphaned documents invisibly to the user.
                document = db.get(Document, document_id)
                if document and document.status in ("processing", "pending"):
                    document.status = "failed"
                    document.quality_status = "failed"
                    document.quality_score = 0.0
                    document.quality_flags_json = ["processing_failed"]
                    document.error_message = truncate_error(exc)
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
        return scan_input_folders(
            db,
            user=None,
            enqueue=True,
            max_examined=settings.watcher_max_files_per_tick,
        )
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.sweep_stale_jobs_task")
def sweep_stale_jobs_task() -> dict:
    """Reset extraction jobs (and their documents) stuck in 'processing'
    for >30 minutes.

    A worker killed mid-processing (between Celery ack and db.commit)
    leaves the job in 'processing' permanently.  This beat task sweeps
    them every 5 minutes so the document can be re-queued.

    Before 2026-07-16 the sweeper only reset the *job* to ``failed``,
    which left the document row stuck in ``processing`` because the
    worker dispatcher filters on ``documents.status = 'pending'``.
    The fix resets the document back to ``pending`` and clears the
    job's error message so the next dispatch picks the document up
    cleanly.  The job itself is left in ``failed`` so its audit
    trail (who started it, when, the killer pid) stays intact.
    """
    from datetime import timedelta

    from sqlalchemy import and_

    from app.models import Document

    db = SessionLocal()
    try:
        cutoff = datetime.now(UTC) - timedelta(minutes=30)
        stale = db.scalars(
            select(ExtractionJob).where(
                and_(
                    ExtractionJob.status == "processing",
                    ExtractionJob.started_at < cutoff,
                )
            )
        ).all()
        reset_count = 0
        documents_reset = 0
        for job in stale:
            document = db.get(Document, job.document_id) if job.document_id else None
            if document is not None and document.status == "processing":
                # SWEEP-1: reset the document back to pending so the
                # next dispatcher tick re-queues it. Preserve the
                # quality_status / quality_score so the user does
                # not lose partial evaluation.
                document.status = "pending"
                document.error_message = None
                documents_reset += 1
            # Mark the original job as failed-but-recoverable. Keep
            # started_at / finished_at so operators can see how
            # long the worker was stuck.
            job.status = "failed"
            job.error_message = "Worker died mid-processing (sweeper timeout)"
            job.finished_at = datetime.now(UTC)
            reset_count += 1
        if reset_count:
            db.commit()
            logger.warning(
                "Sweeper reset %d stale processing jobs (%d documents re-queued)",
                reset_count,
                documents_reset,
            )
            from app.services.metrics.pipeline import track_stale_jobs_reset

            track_stale_jobs_reset(reset_count)
        return {"stale_reset": reset_count, "documents_reset": documents_reset}
    except Exception as exc:
        db.rollback()
        logger.error("Stale job sweeper failed: %s", exc)
        return {"stale_reset": 0, "documents_reset": 0, "error": str(exc)}
    finally:
        db.close()
