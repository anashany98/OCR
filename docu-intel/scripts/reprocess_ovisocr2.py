"""Select and enqueue a bounded, idempotent OvisOCR2 page reprocess batch.

The script never changes the global feature flag.  Operators first enable the
normal Ovis eligibility/canary configuration, inspect this script's dry-run
report, then explicitly pass ``--execute`` for a small batch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import and_, or_, select

# Scripts are executed from the repository root, while the FastAPI package
# lives under backend/.  Keep this local bootstrap instead of requiring an
# operator to remember a PYTHONPATH override for a controlled reprocess.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import settings
from app.database.session import SessionLocal
from app.models import Document, DocumentPage, ExtractionJob
from app.services.document_reprocess_service import reprocess_document_page


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-id", type=int, action="append", default=[])
    parser.add_argument("--page-number", type=int, action="append", default=[])
    parser.add_argument(
        "--reason",
        choices=("low_confidence", "needs_review", "empty"),
        action="append",
        default=[],
        help="Repeat to combine reasons. Defaults to all three.",
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--execute", action="store_true", help="Create and enqueue jobs; dry-run otherwise.")
    parser.add_argument("--report", type=Path, default=Path("artifacts/ovisocr2/reprocess-report.json"))
    return parser.parse_args()


def _pending_page_job_exists(db, page: DocumentPage) -> bool:
    job_type = f"reprocess:ocr_page:{page.page_number}"
    return db.scalar(
        select(ExtractionJob.id)
        .where(ExtractionJob.document_id == page.document_id)
        .where(ExtractionJob.job_type == job_type)
        .where(ExtractionJob.status.in_(("pending", "processing")))
        .limit(1)
    ) is not None


def main() -> int:
    args = _parse_args()
    if args.limit < 1 or args.limit > 500:
        raise SystemExit("--limit must be between 1 and 500")
    reasons = set(args.reason or ("low_confidence", "needs_review", "empty"))
    clauses = []
    if "low_confidence" in reasons:
        clauses.append(
            and_(
                DocumentPage.ocr_confidence.is_not(None),
                DocumentPage.ocr_confidence < settings.low_ocr_confidence_threshold,
            )
        )
    if "needs_review" in reasons:
        clauses.append(
            or_(DocumentPage.ocr_decision == "review_required", Document.status == "needs_review")
        )
    if "empty" in reasons:
        clauses.append(or_(DocumentPage.text.is_(None), DocumentPage.text == ""))
    statement = (
        select(DocumentPage)
        .join(Document, Document.id == DocumentPage.document_id)
        .where(Document.deleted_at.is_(None))
        .where(or_(*clauses))
        .order_by(DocumentPage.document_id.asc(), DocumentPage.page_number.asc())
    )
    if args.document_id:
        statement = statement.where(DocumentPage.document_id.in_(args.document_id))
    if args.page_number:
        statement = statement.where(DocumentPage.page_number.in_(args.page_number))

    db = SessionLocal()
    try:
        selected: list[dict[str, int | str | float | None]] = []
        skipped_existing: list[dict[str, int]] = []
        for page in db.scalars(statement.limit(args.limit * 4)).all():
            if len(selected) >= args.limit:
                break
            entry = {"document_id": page.document_id, "page_number": page.page_number, "confidence": page.ocr_confidence}
            if _pending_page_job_exists(db, page):
                skipped_existing.append({"document_id": page.document_id, "page_number": page.page_number})
                continue
            selected.append(entry)
            if args.execute:
                # This service creates a new immutable attempt and sends exactly
                # one page to the existing OCR-heavy queue; it never replaces a
                # better selected candidate without the normal comparison.
                reprocess_document_page(db, page=page, user=None, enqueue=True)
        report = {
            "mode": "execute" if args.execute else "dry_run",
            "reasons": sorted(reasons),
            "requested_limit": args.limit,
            "selected": selected,
            "selected_count": len(selected),
            "skipped_existing_jobs": skipped_existing,
            "skipped_existing_count": len(skipped_existing),
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
