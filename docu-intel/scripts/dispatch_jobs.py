"""Dispatch all pending extraction jobs to Celery queues."""
from app.database.session import SessionLocal
from app.models import ExtractionJob, Document
from app.workers.tasks import process_document_task
from app.workers.routing import queue_for_document

db = SessionLocal()
pending = db.query(ExtractionJob).filter(ExtractionJob.status == "pending").all()
print(f"Pending jobs: {len(pending)}")

dispatched = 0
failed = 0
for job in pending:
    doc = db.get(Document, job.document_id)
    if not doc:
        continue
    queue = queue_for_document(doc, job.job_type)
    try:
        process_document_task.apply_async(
            args=(doc.id, job.id), queue=queue
        )
        dispatched += 1
    except Exception as e:
        print(f"  Failed job {job.id} for doc {doc.id}: {e}")
        failed += 1

db.close()
print(f"Dispatched: {dispatched}, Failed: {failed}")
