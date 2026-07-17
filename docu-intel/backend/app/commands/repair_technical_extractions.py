"""Backfill durable technical facts for documents already in the corpus."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models import Document, DocumentPage
from app.services.plan_extraction import persist_plan_extraction
from app.services.technical_pipeline import process_technical_document

logger = logging.getLogger("app.commands.repair_technical_extractions")

_TECHNICAL_TYPES = (
    "memoria_descriptiva",
    "memoria_constructiva",
    "medicion",
    "mediciones_obra",
)


def repair_technical_extractions(
    *,
    dry_run: bool = True,
    limit: int | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> dict[str, int]:
    """Replay deterministic plan/memory/measurement extraction idempotently."""
    stats = {"candidates": 0, "updated": 0, "skipped": 0, "errors": 0}
    db = (session_factory or SessionLocal)()
    try:
        query = (
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(
                or_(
                    Document.document_type.like("plano%"),
                    Document.document_type.in_(_TECHNICAL_TYPES),
                )
            )
            .order_by(Document.id)
        )
        if limit is not None:
            query = query.limit(max(limit, 0))
        documents = list(db.scalars(query).all())
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
                if document.document_type.startswith("plano"):
                    persist_plan_extraction(db, document, text)
                process_technical_document(
                    db,
                    document.id,
                    text,
                    document.original_filename,
                    document.document_type,
                    blocks=pages,
                )
                db.commit()
                stats["updated"] += 1
            except Exception:
                db.rollback()
                logger.exception("technical_repair_failed document_id=%s", document.id)
                stats["errors"] += 1
    finally:
        db.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair technical extractions")
    parser.add_argument(
        "--execute", action="store_true", help="Persist changes; default is dry-run"
    )
    parser.add_argument("--limit", type=int, help="Maximum documents to inspect")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(
        json.dumps(
            repair_technical_extractions(dry_run=not args.execute, limit=args.limit),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
