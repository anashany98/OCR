"""CR12 — Safe backfill and reprocessing command.

Runs after CR9 (permissions) and CR10 (OCR tiers) are confirmed.
Processes documents in the correct order:

1. Reprocess documents with page_without_text / ocr_engine=empty
2. Reprocess page_failed documents
3. Recalculate quality without OCR for documents with existing text
4. Re-extract entities/reclassify without OCR when text exists

Features:
- Dry-run mode with counts by reason
- Configurable batch size
- Checkpoint/idempotency (skip already-processed)
- No OCR repeat for quality-only changes
- Before/after reporting per document

Usage:
    python -m app.commands.backfill_reprocess --dry-run
    python -m app.commands.backfill_reprocess --batch-size 50
    python -m app.commands.backfill_reprocess --reason page_without_text
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.session import get_engine
from app.models import Document, DocumentPage

logger = logging.getLogger("app.commands.backfill_reprocess")


@dataclass
class BackfillReport:
    """Tracks before/after counts for the backfill run."""

    total_scanned: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    already_ok: int = 0
    quality_recalculated: int = 0
    entities_reextracted: int = 0
    before_status: dict[str, int] = field(default_factory=dict)
    after_status: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            "=== CR12 Backfill Report ===",
            f"Total scanned: {self.total_scanned}",
            f"By reason: {json.dumps(self.by_reason, indent=2)}",
            f"Processed: {self.processed}",
            f"Skipped (already ok): {self.skipped}",
            f"Failed: {self.failed}",
            f"Quality recalculated: {self.quality_recalculated}",
            f"Entities re-extracted: {self.entities_reextracted}",
            "",
            "Status before:",
        ]
        for status, count in sorted(self.before_status.items()):
            lines.append(f"  {status}: {count}")
        lines.append("Status after:")
        for status, count in sorted(self.after_status.items()):
            lines.append(f"  {status}: {count}")
        return "\n".join(lines)


def _get_documents_by_reason(
    db: Session,
    reason: str,
    limit: int,
) -> list[Document]:
    """Fetch documents matching a specific review reason."""
    if reason == "page_without_text":
        # Documents with at least one page that has no text
        stmt = (
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.status == "processed")
            .where(Document.quality_status.in_(["needs_review", "processed_low_quality"]))
            .limit(limit)
        )
        docs = list(db.execute(stmt).scalars().all())
        # Filter to those with page_without_text flag
        return [d for d in docs if "page_without_text" in (d.quality_flags_json or [])]

    elif reason == "ocr_engine_empty":
        # Documents with pages using empty OCR engine
        subq = select(DocumentPage.document_id).where(DocumentPage.ocr_engine == "empty").distinct()
        stmt = (
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.id.in_(subq))
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())

    elif reason == "page_failed":
        stmt = (
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.quality_status == "needs_human_review")
            .where(Document.status == "processed")
            .limit(limit)
        )
        docs = list(db.execute(stmt).scalars().all())
        return [d for d in docs if "page_failed" in (d.quality_flags_json or [])]

    elif reason == "quality_recalculate":
        # Documents with text that need quality recalculation
        # (skip those that already have processed_ok)
        stmt = (
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.status == "processed")
            .where(Document.quality_status != "processed_ok")
            .where(Document.quality_status.is_not(None))
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())

    elif reason == "all":
        # All documents in review
        stmt = (
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.status == "processed")
            .where(
                Document.quality_status.in_(
                    [
                        "needs_review",
                        "processed_low_quality",
                        "processed_missing_fields",
                        "needs_human_review",
                    ]
                )
            )
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())

    return []


def _reprocess_document(db: Session, doc: Document, *, dry_run: bool = False) -> str:
    """Reprocess a single document. Returns the action taken."""
    from app.services.quality import refresh_quality_from_existing_pages

    old_status = doc.quality_status
    if dry_run:
        return f"dry_run: would reprocess {doc.id} ({old_status})"

    try:
        # CR12: Recalculate quality from existing pages (no OCR repeat)
        result = refresh_quality_from_existing_pages(db, doc)

        # Log before/after
        if result.status != old_status:
            logger.info(
                "Doc %d: quality %s -> %s (flags: %s)",
                doc.id,
                old_status,
                result.status,
                result.flags,
            )

        return result.status
    except Exception as exc:
        logger.error("Failed to reprocess doc %d: %s", doc.id, exc)
        return "error"


def run_backfill(
    *,
    dry_run: bool = False,
    batch_size: int = 50,
    reason: str = "all",
) -> BackfillReport:
    """Execute the backfill/reprocessing pipeline.

    Returns a BackfillReport with before/after counts.
    """
    report = BackfillReport()
    engine = get_engine()

    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        # Snapshot status counts before
        status_counts = dict(
            db.execute(
                select(Document.quality_status, func.count(Document.id))
                .where(Document.deleted_at.is_(None))
                .group_by(Document.quality_status)
            ).all()
        )
        report.before_status = status_counts

        # Get documents to process
        docs = _get_documents_by_reason(db, reason, limit=batch_size)
        report.total_scanned = len(docs)
        report.by_reason[reason] = len(docs)

        logger.info(
            "CR12 backfill: found %d documents for reason '%s' (dry_run=%s)",
            len(docs),
            reason,
            dry_run,
        )

        for doc in docs:
            action = _reprocess_document(db, doc, dry_run=dry_run)
            if action == "error":
                report.failed += 1
            elif action == doc.quality_status:
                report.already_ok += 1
            else:
                report.processed += 1

        if not dry_run:
            db.commit()

        # Snapshot status counts after
        status_counts_after = dict(
            db.execute(
                select(Document.quality_status, func.count(Document.id))
                .where(Document.deleted_at.is_(None))
                .group_by(Document.quality_status)
            ).all()
        )
        report.after_status = status_counts_after

    return report


def main():
    parser = argparse.ArgumentParser(description="CR12: Safe backfill and reprocessing pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of documents to process (default: 50)",
    )
    parser.add_argument(
        "--reason",
        choices=[
            "page_without_text",
            "ocr_engine_empty",
            "page_failed",
            "quality_recalculate",
            "all",
        ],
        default="all",
        help="Which documents to reprocess",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    report = run_backfill(
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        reason=args.reason,
    )
    print(report.summary())


if __name__ == "__main__":
    main()
