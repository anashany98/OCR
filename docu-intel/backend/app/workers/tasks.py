from app.database.session import SessionLocal
from app.ingestion.scanner import scan_input_folders
from app.models import Document, ExtractionJob
from app.services.document_service import process_document
from app.services.notification import notification_service
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.process_document_task", bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=2)
def process_document_task(self, document_id: int, job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(ExtractionJob, job_id)
        if job and hasattr(job, "retries"):
            job.retries = int(getattr(self.request, "retries", 0) or 0)
            db.commit()
        process_document(db, document_id=document_id, job_id=job_id)
    except Exception as exc:
        document = db.get(Document, document_id)
        if document:
            notification_service.notify_job_failed(job_id, document_id, str(exc))
        raise
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.scan_input_folders_task")
def scan_input_folders_task() -> dict:
    db = SessionLocal()
    try:
        return scan_input_folders(db, user=None, enqueue=True)
    finally:
        db.close()
