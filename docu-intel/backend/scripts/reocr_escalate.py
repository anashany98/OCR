"""FASE 3.4: Re-OCR pages that now fail the raised cascade thresholds.

Selects tesseract pages where chars < 150 OR confidence < 0.70,
enqueues reprocess:ocr jobs for their parent documents, and prints
a summary.

Usage (inside the backend container):
    docker compose exec backend python scripts/reocr_escalate.py [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models import Document, DocumentPage, ExtractionJob
from app.services.audit import write_audit
from app.services.document_processing_core import processing_mode_from_job_type

logger = logging.getLogger("reocr_escalate")


def find_escalation_candidates(db: Session) -> list[int]:
    """Return document IDs whose tesseract pages fail the new thresholds."""
    rows = db.execute(
        text("""
            SELECT DISTINCT dp.document_id
            FROM document_pages dp
            JOIN documents d ON d.id = dp.document_id
            WHERE dp.ocr_engine IN ('tesseract', 'pymupdf')
              AND d.deleted_at IS NULL
              AND (
                LENGTH(TRIM(COALESCE(dp.text, ''))) < 150
                OR dp.ocr_confidence < 0.70
              )
            ORDER BY dp.document_id
        """)
    ).scalars().all()
    return list(rows)


def enqueue_reocr(db: Session, document_ids: list[int], dry_run: bool = False) -> dict:
    """Enqueue reprocess:ocr jobs for the given documents."""
    active_jobs = int(
        db.scalar(
            select(func.count())
            .select_from(ExtractionJob)
            .where(ExtractionJob.status.in_(["pending", "processing"]))
        )
        or 0
    )

    enqueued = 0
    skipped = 0
    job_ids = []
    limit = 500  # safety cap

    for doc_id in document_ids[:limit]:
        doc = db.get(Document, doc_id)
        if doc is None:
            skipped += 1
            continue

        has_active = db.scalar(
            select(func.count())
            .select_from(ExtractionJob)
            .where(ExtractionJob.document_id == doc_id)
            .where(ExtractionJob.status.in_(["pending", "processing"]))
        )
        if has_active:
            skipped += 1
            continue

        if dry_run:
            enqueued += 1
            continue

        doc.status = "pending"
        doc.quality_status = "pending"
        doc.quality_flags_json = []
        doc.error_message = None

        job = ExtractionJob(
            document_id=doc_id,
            job_type="reprocess:ocr",
            status="pending",
        )
        db.add(job)
        db.flush()
        job_ids.append(job.id)

        from app.workers.routing import queue_for_document
        from app.workers.tasks import process_document_task

        process_document_task.apply_async(
            args=(doc_id, job.id),
            queue=queue_for_document(doc, job.job_type),
        )
        enqueued += 1
        active_jobs += 1

    if not dry_run:
        write_audit(
            db,
            user=None,
            action="fase3_reocr_escalation",
            entity_type="operations",
            details={
                "target_documents": len(document_ids),
                "enqueued": enqueued,
                "skipped": skipped,
            },
        )
        db.commit()

    return {
        "target_documents": len(document_ids),
        "enqueued": enqueued,
        "skipped": skipped,
        "job_ids": job_ids,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-OCR pages failing new thresholds")
    parser.add_argument("--dry-run", action="store_true", help="Preview without enqueuing")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        doc_ids = find_escalation_candidates(db)
        print(f"Candidate documents: {len(doc_ids)}")

        if not doc_ids:
            print("Nothing to do.")
            return 0

        result = enqueue_reocr(db, doc_ids, dry_run=args.dry_run)
        print(f"Enqueued: {result['enqueued']}")
        print(f"Skipped (active job or missing): {result['skipped']}")
        if args.dry_run:
            print("(dry run — nothing was actually enqueued)")
        else:
            print(f"Job IDs: {result['job_ids'][:10]}{'...' if len(result['job_ids']) > 10 else ''}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
