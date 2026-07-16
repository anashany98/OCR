"""Backfill structured business records after occurrence association repair."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models import Budget, Document, DocumentPage
from app.models.project import DocumentOccurrence
from app.services.business_extraction import persist_business_extraction

logger = logging.getLogger("app.commands.repair_contextual_business_extractions")


def repair_contextual_business_extractions(
    *,
    dry_run: bool = True,
    limit: int | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> dict[str, int]:
    """Fill missing structured budget identity from verified occurrence data.

    The normal extractor remains the source for document-derived values.  This
    command only replays it after the contextual association exists, allowing
    the extractor to use its conservative folder-identity fallback.
    """
    stats = {"candidates": 0, "updated": 0, "skipped": 0, "errors": 0}
    db = (session_factory or SessionLocal)()
    try:
        query = (
            select(Document)
            .join(Budget, Budget.document_id == Document.id)
            .join(DocumentOccurrence, DocumentOccurrence.document_id == Document.id)
            .where(Document.deleted_at.is_(None))
            .where(Document.document_type == "presupuesto")
            .where(Budget.budget_number.is_(None))
            .where(DocumentOccurrence.resolved_budget_code.is_not(None))
            .where(DocumentOccurrence.association_status.in_(("verified", "folder_only", "content_only")))
            .order_by(Document.id)
        )
        if limit is not None:
            query = query.limit(max(0, limit))
        documents = list(db.scalars(query).unique().all())
        stats["candidates"] = len(documents)
        if dry_run:
            return stats
        for document in documents:
            pages = list(
                db.scalars(
                    select(DocumentPage)
                    .where(DocumentPage.document_id == document.id)
                    .order_by(DocumentPage.page_number)
                ).all()
            )
            text = "\n".join(page.text or "" for page in pages).strip()
            if not text:
                stats["skipped"] += 1
                continue
            try:
                result = persist_business_extraction(db, document, text, pages=pages)
                if result.budget is not None and result.budget.budget_number:
                    stats["updated"] += 1
                else:
                    stats["skipped"] += 1
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("contextual_business_repair_failed document_id=%s", document.id)
                stats["errors"] += 1
    finally:
        db.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair contextual business extraction")
    parser.add_argument("--execute", action="store_true", help="Persist rows; default is dry-run")
    parser.add_argument("--limit", type=int, help="Maximum documents to inspect")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(
        json.dumps(
            repair_contextual_business_extractions(dry_run=not args.execute, limit=args.limit),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
