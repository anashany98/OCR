#!/usr/bin/env python3
"""Enqueue documents for reprocess:full.

By default this reprocesses ALL non-deleted documents, which is a destructive
operation at scale (it re-OCRs and re-embeds everything). Use ``--dry-run``
first to preview the impact, and ``--limit`` to bound a batch.

Examples::

    # Preview what would be reprocessed (no changes)
    python scripts/reprocess_all.py --dry-run

    # Reprocess the first 200 documents
    python scripts/reprocess_all.py --limit 200

    # Reprocess everything (use with care)
    python scripts/reprocess_all.py
"""
import argparse

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import Document, ExtractionJob
from app.workers.routing import queue_for_document
from app.workers.tasks import process_document_task


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enqueue documents for reprocess:full.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be reprocessed; do not create or enqueue jobs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of documents to enqueue (0 = no limit).",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        # Get all non-deleted documents
        docs = list(
            db.scalars(
                select(Document)
                .where(Document.deleted_at.is_(None))
                .order_by(Document.id)
            ).all()
        )
        if args.limit > 0:
            docs = docs[: args.limit]

        print(f"Total documents selected: {len(docs)}")

        if args.dry_run:
            print("[DRY RUN] no jobs will be created or enqueued.")
            active = db.scalar(
                select(ExtractionJob.document_id)
                .where(ExtractionJob.status.in_(["pending", "processing"]))
            )
            skipped_preview = 0
            for doc in docs:
                has_active = (
                    db.scalar(
                        select(ExtractionJob.id)
                        .where(ExtractionJob.document_id == doc.id)
                        .where(ExtractionJob.status.in_(["pending", "processing"]))
                        .limit(1)
                    )
                    is not None
                )
                if has_active:
                    skipped_preview += 1
            print(f"[DRY RUN] would enqueue: {len(docs) - skipped_preview}")
            print(f"[DRY RUN] would skip (active job): {skipped_preview}")
            return

        # Check which already have active jobs
        active_jobs = list(
            db.scalars(
                select(ExtractionJob.document_id).where(
                    ExtractionJob.status.in_(["pending", "processing"])
                )
            ).all()
        )
        active_doc_ids = set(active_jobs)

        enqueued = 0
        skipped = 0

        for doc in docs:
            if doc.id in active_doc_ids:
                skipped += 1
                continue

            # Create reprocess:full job
            job = ExtractionJob(
                document_id=doc.id,
                job_type="reprocess:full",
                status="pending",
            )
            db.add(job)
            db.flush()

            # Enqueue to Celery
            process_document_task.apply_async(
                args=(doc.id, job.id),
                queue=queue_for_document(doc, job.job_type),
            )
            enqueued += 1

        db.commit()
        print(f"Enqueued: {enqueued}")
        print(f"Skipped (active job): {skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
