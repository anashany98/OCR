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
import sys
import time
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import SessionLocal
from app.models.budget_scope import BudgetScope
from app.models.document import Document
from app.models.project import DocumentOccurrence, Project
from app.models.tenant import Hotel, HotelChain
from app.services.project_path_resolver import classify_category, resolve_corpus_path

logger = logging.getLogger("app.commands.backfill_corpus")

# Checkpoint file
CHECKPOINT_FILE = Path("data/backfill_checkpoint.json")


def _load_checkpoint() -> dict[str, Any]:
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {"last_path": None, "processed": 0, "skipped": 0, "errors": 0}


def _save_checkpoint(checkpoint: dict[str, Any]) -> None:
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(checkpoint, indent=2))


def _find_or_create_brand(db: Session, name: str) -> HotelChain:
    brand = db.scalar(select(HotelChain).where(HotelChain.name == name))
    if not brand:
        brand = HotelChain(name=name)
        db.add(brand)
        db.flush()
    return brand


def _find_or_create_hotel(db: Session, name: str, brand_id: int) -> Hotel:
    hotel = db.scalar(
        select(Hotel).where(Hotel.name == name, Hotel.chain_id == brand_id)
    )
    if not hotel:
        hotel = Hotel(name=name, chain_id=brand_id)
        db.add(hotel)
        db.flush()
    return hotel


def _find_or_create_budget(db: Session, code: str) -> BudgetScope:
    bs = db.scalar(select(BudgetScope).where(BudgetScope.budget_code == code))
    if not bs:
        bs = BudgetScope(budget_code=code)
        db.add(bs)
        db.flush()
    return bs


def _find_or_create_project(
    db: Session, brand_id: int, hotel_id: int | None, budget_scope_id: int | None, year: int
) -> Project:
    stmt = select(Project).where(
        Project.brand_id == brand_id,
        Project.year == year,
    )
    if hotel_id:
        stmt = stmt.where(Project.hotel_id == hotel_id)
    else:
        stmt = stmt.where(Project.hotel_id.is_(None))
    project = db.scalar(stmt)
    if not project:
        project = Project(
            brand_id=brand_id,
            hotel_id=hotel_id,
            year=year,
            name=f"Project {year}/{brand_id}",
            primary_budget_scope_id=budget_scope_id,
        )
        db.add(project)
        db.flush()
    return project


def run_backfill(
    *,
    dry_run: bool = True,
    limit: int | None = None,
    full: bool = False,
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

    checkpoint = _load_checkpoint() if not full else {"last_path": None, "processed": 0, "skipped": 0, "errors": 0}
    start_from = checkpoint.get("last_path")

    stats = {
        "total_files": 0,
        "processed": checkpoint.get("processed", 0),
        "skipped": checkpoint.get("skipped", 0),
        "errors": checkpoint.get("errors", 0),
        "brands_created": 0,
        "hotels_created": 0,
        "budgets_created": 0,
        "projects_created": 0,
        "occurrences_created": 0,
    }

    logger.info("Starting backfill from %s (dry_run=%s, limit=%s)", source_root, dry_run, limit)

    db = SessionLocal() if not dry_run else None
    try:
        for path in Path(source_root).rglob("*"):
            if not path.is_file():
                continue

            stats["total_files"] += 1
            source_path = str(path)

            # Resume from checkpoint
            if start_from and source_path <= start_from:
                continue

            if limit and stats["processed"] >= limit:
                break

            try:
                resolution = resolve_corpus_path(source_path, source_root)
                category = classify_category(path.name, resolution.category)

                if not resolution.brand:
                    stats["skipped"] += 1
                    continue

                if db:
                    # Create/find entities
                    brand = _find_or_create_brand(db, resolution.brand)
                    hotel = None
                    if resolution.hotel:
                        hotel = _find_or_create_hotel(db, resolution.hotel, brand.id)
                        if hotel.id:
                            stats["hotels_created"] += 1

                    budget_scope = None
                    if resolution.budget_code:
                        budget_scope = _find_or_create_budget(db, resolution.budget_code)
                        if budget_scope.id:
                            stats["budgets_created"] += 1

                    project = _find_or_create_project(
                        db, brand.id, hotel.id if hotel else None,
                        budget_scope.id if budget_scope else None,
                        resolution.year or 2025,
                    )
                    if project.id:
                        stats["projects_created"] += 1

                    # Find existing document by source_path
                    existing_doc = db.scalar(
                        select(Document).where(Document.source_path == source_path)
                    )

                    # Check if occurrence already exists
                    existing_occ = db.scalar(
                        select(DocumentOccurrence).where(
                            DocumentOccurrence.source_root == source_root,
                            DocumentOccurrence.source_path == source_path,
                        )
                    )
                    if existing_occ:
                        stats["skipped"] += 1
                        continue

                    if existing_doc:
                        occ = DocumentOccurrence(
                            document_id=existing_doc.id,
                            source_path=source_path,
                            source_root=source_root,
                            year=resolution.year or 2025,
                            brand_id=brand.id,
                            hotel_id=hotel.id if hotel else None,
                            budget_scope_id=budget_scope.id if budget_scope else None,
                            project_id=project.id,
                            category=category,
                            original_filename=path.name,
                        )
                        db.add(occ)
                        stats["occurrences_created"] += 1
                    else:
                        # Will be created when document is ingested
                        stats["skipped"] += 1

                    stats["processed"] += 1

                    # Checkpoint every 100 files
                    if stats["processed"] % 100 == 0:
                        db.commit()
                        checkpoint["last_path"] = source_path
                        checkpoint.update(stats)
                        _save_checkpoint(checkpoint)
                        logger.info("Checkpoint: %s files processed", stats["processed"])
                else:
                    # Dry run - just count
                    stats["processed"] += 1

            except Exception as e:
                stats["errors"] += 1
                logger.warning("Error processing %s: %s", source_path, e)
                if db:
                    db.rollback()

        if db:
            db.commit()
            checkpoint["last_path"] = None
            checkpoint.update(stats)
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
    args = parser.parse_args()

    dry_run = not args.execute
    logging.basicConfig(level=logging.INFO)

    stats = run_backfill(dry_run=dry_run, limit=args.limit, full=args.full)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
