#!/usr/bin/env python3
"""Re-enqueue pending extraction jobs to Celery.

Originally a one-shot script with a hard-coded ``id >= 12134`` threshold from
a specific incident. It now accepts a ``--min-job-id`` so it can be reused for
any future incident without editing the source.

Examples::

    # Dry-run: preview what would be re-enqueued
    python scripts/reenqueue_pending.py --dry-run

    # Re-enqueue all pending jobs with id >= 12134 (the incident threshold)
    python scripts/reenqueue_pending.py --min-job-id 12134

    # Re-enqueue ALL pending jobs regardless of id
    python scripts/reenqueue_pending.py --min-job-id 0
"""
import argparse

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import Document, ExtractionJob
from app.workers.routing import queue_for_document
from app.workers.tasks import process_document_task


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-enqueue pending extraction jobs to Celery.",
    )
    parser.add_argument(
        "--min-job-id",
        type=int,
        default=12134,
        help="Only re-enqueue jobs with id >= this value (default 12134, the "
        "original incident threshold; pass 0 for all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be re-enqueued; do not enqueue.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        jobs = list(
            db.scalars(
                select(ExtractionJob)
                .where(ExtractionJob.id >= args.min_job_id)
                .where(ExtractionJob.status == "pending")
            ).all()
        )
        print(f"Pending jobs with id >= {args.min_job_id}: {len(jobs)}")

        if args.dry_run:
            print("[DRY RUN] no jobs will be re-enqueued.")
            return

        enqueued = 0
        for job in jobs:
            doc = db.get(Document, job.document_id)
            if doc is None:
                continue
            process_document_task.apply_async(
                args=(doc.id, job.id),
                queue=queue_for_document(doc, job.job_type),
            )
            enqueued += 1

        print(f"Enqueued {enqueued} jobs")
    finally:
        db.close()


if __name__ == "__main__":
    main()
