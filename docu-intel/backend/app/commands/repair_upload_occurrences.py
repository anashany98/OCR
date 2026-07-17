"""Repair project occurrences for already-ingested hierarchical uploads.

Older uploads were intentionally excluded from corpus association.  They can
still carry an explicit ``upload/<namespace>/Brand/.../Presupuesto ...`` path,
so this command materialises that context without re-uploading bytes, running
OCR, or touching the source corpus.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models import Document, DocumentOccurrence
from app.services.document_registration_service import _create_occurrence, _occurrence_source_root
from app.services.project_path_resolver import resolve_corpus_path

logger = logging.getLogger("app.commands.repair_upload_occurrences")


def repair_upload_occurrences(
    *,
    dry_run: bool = True,
    limit: int | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> dict[str, int]:
    """Associate unlinked hierarchical uploads idempotently.

    ``dry_run`` never opens a write transaction and reports only paths that
    contain a resolvable brand plus a budget code.  The executed mode commits
    each document independently so one malformed legacy row cannot roll back
    the rest of the repair.
    """
    stats = {"candidates": 0, "eligible": 0, "created": 0, "skipped": 0, "errors": 0}
    db = (session_factory or SessionLocal)()
    try:
        query = (
            select(Document)
            .outerjoin(DocumentOccurrence, DocumentOccurrence.document_id == Document.id)
            .where(Document.deleted_at.is_(None))
            .where(Document.duplicate_of_document_id.is_(None))
            .where(Document.source_path.ilike("upload/%"))
            .where(DocumentOccurrence.id.is_(None))
            .order_by(Document.id)
        )
        if limit is not None:
            query = query.limit(max(0, limit))
        documents = list(db.scalars(query).all())
        stats["candidates"] = len(documents)
        for document in documents:
            source_path = document.source_path or ""
            root = _occurrence_source_root(source_path)
            resolution = resolve_corpus_path(source_path, root or "") if root else None
            if resolution is None or not resolution.brand or not resolution.budget_code:
                stats["skipped"] += 1
                continue
            stats["eligible"] += 1
            if dry_run:
                continue
            try:
                with db.begin_nested():
                    # ``_create_occurrence`` uses the path only as immutable
                    # metadata here; no source file is opened or modified.
                    occurrence = _create_occurrence(
                        db,
                        document,
                        Path(source_path.replace("\\", "/").rsplit("/", 1)[-1]),
                        source_path,
                    )
                    if occurrence is None:
                        stats["skipped"] += 1
                    else:
                        stats["created"] += 1
            except Exception:
                logger.exception("upload_occurrence_repair_failed document_id=%s", document.id)
                stats["errors"] += 1
        if not dry_run:
            db.commit()
    finally:
        db.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair hierarchical upload occurrences")
    parser.add_argument(
        "--execute", action="store_true", help="Persist occurrences; default is dry-run"
    )
    parser.add_argument("--limit", type=int, help="Maximum documents to inspect")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(
        json.dumps(repair_upload_occurrences(dry_run=not args.execute, limit=args.limit), indent=2)
    )


if __name__ == "__main__":
    main()
