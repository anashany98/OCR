from celery.exceptions import Reject

from app.database.session import SessionLocal
from app.ingestion.scanner import scan_input_folders
from app.models import Document, ExtractionJob
from app.services.document_service import process_document
from app.services.notification import notification_service
from app.workers.celery_app import celery_app
from app.workers.errors import (
    RETRYABLE_EXCEPTIONS,
    is_permanent,
    mark_job_as_failed,
    notify_failed,
)


@celery_app.task(
    name="app.workers.tasks.process_document_task",
    bind=True,
    autoretry_for=RETRYABLE_EXCEPTIONS,  # WRK-RETRY-1: narrow allow-list
    retry_backoff=True,
    retry_backoff_max=300,             # cap the exponential backoff at 5 min
    retry_jitter=True,                  # avoid thundering herd on retry
    max_retries=3,
    soft_time_limit=900,                # 15 min soft kill (SIGTERM, can clean up)
    time_limit=1200,                    # 20 min hard kill (SIGKILL)
    acks_late=True,                     # ack only after work is done
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
                raise Reject(exc, requeue=False)
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
