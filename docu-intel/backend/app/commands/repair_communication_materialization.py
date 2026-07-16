"""Repair source-backed communication records from already parsed email files."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models import Document, DocumentPage
from app.services.communication_ingestion import materialize_communication

logger = logging.getLogger("app.commands.repair_communication_materialization")

_EMAIL_EXTENSIONS = (".eml", ".msg")


def repair_communication_materialization(
    *,
    dry_run: bool = True,
    limit: int | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> dict[str, int]:
    """Replay email materialisation from durable document-page text.

    Only documents are candidates.  Legacy records that have no
    ``document_id`` are deliberately not guessed or repurposed: they lack
    immutable provenance and require the separate, explicit cleanup mode.
    """
    stats = {"candidates": 0, "updated": 0, "skipped": 0, "errors": 0}
    db = (session_factory or SessionLocal)()
    try:
        query = (
            select(Document)
            .where(Document.deleted_at.is_(None))
            .where(Document.extension.in_(_EMAIL_EXTENSIONS))
            .order_by(Document.id)
        )
        if limit is not None:
            query = query.limit(max(limit, 0))
        documents = list(db.scalars(query).all())
        stats["candidates"] = len(documents)
        if dry_run:
            return stats
        for document in documents:
            text = "\n".join(
                db.scalars(
                    select(DocumentPage.text)
                    .where(DocumentPage.document_id == document.id)
                    .order_by(DocumentPage.page_number)
                ).all()
            ).strip()
            if not text:
                stats["skipped"] += 1
                continue
            try:
                materialize_communication(db, document, text=text)
                db.commit()
                stats["updated"] += 1
            except Exception:
                db.rollback()
                logger.exception("communication_repair_failed document_id=%s", document.id)
                stats["errors"] += 1
    finally:
        db.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair source-backed communications")
    parser.add_argument("--execute", action="store_true", help="Persist changes; default is dry-run")
    parser.add_argument("--limit", type=int, help="Maximum documents to inspect")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(
        json.dumps(
            repair_communication_materialization(dry_run=not args.execute, limit=args.limit),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
