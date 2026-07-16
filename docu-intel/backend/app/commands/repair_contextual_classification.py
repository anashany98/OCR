"""Reclassify legacy image documents using their persisted folder context."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models import Document, DocumentOccurrence

logger = logging.getLogger("app.commands.repair_contextual_classification")

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")
_BUSINESS_TYPES = ("presupuesto", "pedido", "factura", "albaran")


def repair_contextual_classifications(
    *,
    dry_run: bool = True,
    limit: int | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> dict[str, int]:
    """Repair images previously classified from a parent budget folder.

    The normal classification-only path also deletes obsolete business rows,
    recalculates quality and refreshes enrichment.  No OCR or source files are
    touched, making this safe for already-ingested documents.
    """
    stats = {"candidates": 0, "reclassified": 0, "unchanged": 0, "errors": 0}
    db = (session_factory or SessionLocal)()
    try:
        query = (
            select(Document)
            .join(DocumentOccurrence, DocumentOccurrence.document_id == Document.id)
            .where(Document.deleted_at.is_(None))
            .where(Document.duplicate_of_document_id.is_(None))
            .where(Document.extension.in_(_IMAGE_EXTENSIONS))
            .where(DocumentOccurrence.category == "imagenes")
            .where(Document.document_type.in_(_BUSINESS_TYPES))
            .order_by(Document.id)
        )
        if limit is not None:
            query = query.limit(max(0, limit))
        documents = list(db.scalars(query).unique().all())
        stats["candidates"] = len(documents)
        if dry_run:
            return stats
        from app.services.document_processing_core import _process_classification_only

        for document in documents:
            previous_type = document.document_type
            try:
                _process_classification_only(db, document)
                if document.document_type == previous_type:
                    stats["unchanged"] += 1
                else:
                    stats["reclassified"] += 1
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("contextual_reclassification_failed document_id=%s", document.id)
                stats["errors"] += 1
    finally:
        db.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair classification of hierarchical upload images")
    parser.add_argument("--execute", action="store_true", help="Persist classifications; default is dry-run")
    parser.add_argument("--limit", type=int, help="Maximum documents to inspect")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(
        json.dumps(
            repair_contextual_classifications(dry_run=not args.execute, limit=args.limit),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
