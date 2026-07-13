#!/usr/bin/env python3
"""Phase 11 — Corpus backfill script.

Resolves paths, creates brands/hotels/budgets/projects/occurrences
without OCR. Dry-run by default. Resumable via checkpoint.

Usage:
    python -m app.commands.backfill_corpus --dry-run
    python -m app.commands.backfill_corpus --limit 100
    python -m app.commands.backfill_corpus --full
"""

from __future__ import annotations

import argparse
import json
import logging
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import SessionLocal
from app.models.document import Document
from app.models.project import DocumentOccurrence
from app.services.document_registration_service import _create_occurrence
from app.services.file_storage import calculate_sha256
from app.services.project_path_resolver import resolve_corpus_path

logger = logging.getLogger("app.commands.backfill_corpus")

# Checkpoint file
CHECKPOINT_FILE = Path("data/backfill_checkpoint.json")
CHECKPOINT_VERSION = 1


def _new_checkpoint(source_root: str) -> dict[str, Any]:
    return {
        "version": CHECKPOINT_VERSION,
        "source_root": source_root,
        "last_path": None,
        "processed": 0,
        "skipped": 0,
        "errors": 0,
    }


def _load_checkpoint(source_root: str) -> dict[str, Any]:
    """Load only a checkpoint that belongs to this exact corpus root."""
    if not CHECKPOINT_FILE.exists():
        return _new_checkpoint(source_root)
    try:
        checkpoint = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable backfill checkpoint: %s", exc)
        return _new_checkpoint(source_root)
    if (
        checkpoint.get("version") != CHECKPOINT_VERSION
        or checkpoint.get("source_root") != source_root
    ):
        logger.warning("Ignoring checkpoint for a different corpus/version")
        return _new_checkpoint(source_root)
    return checkpoint


def _save_checkpoint(checkpoint: dict[str, Any]) -> None:
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=CHECKPOINT_FILE.parent,
        prefix=f".{CHECKPOINT_FILE.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(checkpoint, handle, indent=2, sort_keys=True)
        temporary_path = Path(handle.name)
    temporary_path.replace(CHECKPOINT_FILE)


def run_backfill(
    *,
    dry_run: bool = True,
    limit: int | None = None,
    full: bool = False,
    sample: int | None = None,
    validate_only: bool = False,
    session_factory: Callable[[], Session] | None = None,
) -> dict[str, Any]:
    """Run the corpus backfill.

    Args:
        dry_run: If True, don't write to DB.
        limit: Max files to process.
        full: If True, ignore checkpoint and start from beginning.

    Returns:
        Statistics dict.
    """
    source_root = str(settings.source_corpus_dir)
    if not Path(source_root).is_dir():
        logger.error("Source corpus not found: %s", source_root)
        return {"error": "source_not_found"}

    if validate_only:
        dry_run = True
    checkpoint = _load_checkpoint(source_root) if not full else _new_checkpoint(source_root)
    start_from = checkpoint.get("last_path")

    stats = {
        "run_id": str(uuid4()),
        "total_files": 0,
        "processed": checkpoint.get("processed", 0),
        "skipped": checkpoint.get("skipped", 0),
        "errors": checkpoint.get("errors", 0),
        "brands_created": 0,
        "hotels_created": 0,
        "budgets_created": 0,
        "projects_created": 0,
        "occurrences_created": 0,
        "found": 0,
        "linked_by_path": 0,
        "linked_by_sha": 0,
        "validated": 0,
        "bytes_hashed": 0,
        "conflicts": 0,
        "validate_only": validate_only,
        "stopped_on_error": False,
    }

    logger.info("Starting backfill from %s (dry_run=%s, limit=%s)", source_root, dry_run, limit)

    db = (session_factory or SessionLocal)() if not dry_run else None
    processed_this_run = 0
    last_successful_path = start_from
    try:
        files = (
            path
            for path in sorted(Path(source_root).rglob("*"), key=lambda candidate: str(candidate))
            if path.is_file()
        )
        if sample is not None:
            from itertools import islice

            files = islice(files, max(0, sample))
        for path in files:
            stats["total_files"] += 1
            source_path = str(path)

            # Resume from checkpoint
            if start_from and source_path <= start_from:
                continue

            if limit is not None and processed_this_run >= limit:
                break

            try:
                resolution = resolve_corpus_path(source_path, source_root)

                if not resolution.brand:
                    stats["skipped"] += 1
                    processed_this_run += 1
                    last_successful_path = source_path
                    continue
                stats["found"] += 1

                if db:
                    with db.begin_nested():
                        existing_occurrence = db.scalar(
                            select(DocumentOccurrence).where(
                                DocumentOccurrence.source_root == source_root,
                                DocumentOccurrence.source_path == source_path,
                            )
                        )
                        if existing_occurrence:
                            stats["skipped"] += 1
                        else:
                            existing_document = db.scalar(
                                select(Document).where(Document.source_path == source_path)
                            )
                            linked_by = "path"
                            if existing_document is None:
                                file_hash = calculate_sha256(path)
                                stats["bytes_hashed"] += path.stat().st_size
                                existing_document = db.scalar(
                                    select(Document)
                                    .where(Document.file_hash == file_hash)
                                    .where(Document.deleted_at.is_(None))
                                    .where(Document.status.notin_(["duplicate", "failed"]))
                                    .order_by(Document.id.asc())
                                )
                                linked_by = "sha"
                            if existing_document is None:
                                # Backfill links already-ingested documents only.  Creating a
                                # Document here would duplicate ingestion and start OCR work.
                                stats["skipped"] += 1
                            else:
                                occurrence = _create_occurrence(
                                    db, existing_document, path, source_path
                                )
                                if occurrence is None:
                                    stats["skipped"] += 1
                                else:
                                    stats[f"linked_by_{linked_by}"] += 1
                                    stats["occurrences_created"] += 1
                else:
                    # Dry-run only validates the resolver and never opens a DB session,
                    # writes a checkpoint, or modifies the corpus.
                    stats["validated"] += 1

                processed_this_run += 1
                stats["processed"] += 1
                last_successful_path = source_path

                if db and processed_this_run % 100 == 0:
                    db.commit()
                    checkpoint.update(stats)
                    checkpoint["last_path"] = last_successful_path
                    _save_checkpoint(checkpoint)
                    logger.info("Checkpoint: %s files processed", stats["processed"])

            except Exception as e:
                stats["errors"] += 1
                stats["stopped_on_error"] = True
                logger.warning("Error processing %s: %s", source_path, e)
                if db:
                    db.rollback()
                # Do not advance the cursor past a failing path.  A resume must
                # retry it instead of silently losing its membership.
                break

        if db:
            db.commit()
            checkpoint.update(stats)
            checkpoint["last_path"] = last_successful_path
            _save_checkpoint(checkpoint)

    finally:
        if db:
            db.close()

    logger.info("Backfill complete: %s", json.dumps(stats, indent=2))
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Corpus backfill script")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Dry run (default)")
    parser.add_argument("--execute", action="store_true", help="Actually write to DB")
    parser.add_argument("--limit", type=int, help="Max files to process")
    parser.add_argument("--full", action="store_true", help="Ignore checkpoint, start fresh")
    parser.add_argument(
        "--sample", type=int, help="Deterministic number of corpus files to inspect"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate paths and counts without DB/checkpoint writes",
    )
    args = parser.parse_args()

    dry_run = not args.execute
    logging.basicConfig(level=logging.INFO)

    stats = run_backfill(
        dry_run=dry_run,
        limit=args.limit,
        full=args.full,
        sample=args.sample,
        validate_only=args.validate_only,
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
