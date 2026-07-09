"""Reclassify all documents using the improved classification rules.

This script re-evaluates document_type for all documents without re-running OCR.
It uses the existing OCR text stored in the database and applies the new
classification logic (word boundaries, dedup, image guard, cross-validation).

Usage:
    python -m scripts.reclassify_documents [--dry-run] [--verbose]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.database.session import get_db
from app.models.document import Document
from app.services.classification import (
    LearnedRule,
    classify_document,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def get_learned_rules(db) -> list[LearnedRule]:
    """Fetch learned rules from the database."""
    try:
        from app.models.learning import LearnedPattern

        patterns = db.scalars(
            select(LearnedPattern).where(LearnedPattern.status == "active")
        ).all()

        return [
            LearnedRule(
                pattern_value=p.pattern_value,
                target_class=p.target_class,
                confidence=p.confidence,
                source="learned",
            )
            for p in patterns
        ]
    except Exception as exc:
        logger.warning("Could not load learned rules: %s", exc)
        return []


def reclassify_all(dry_run: bool = False, verbose: bool = False, only_unknown: bool = True, doc_type: str | None = None) -> dict:
    """Reclassify documents and report changes.

    By default only ``desconocido`` documents are reclassified, since those
    are the ones the new rules can actually resolve. Reclassifying already
    classified documents (invoices, budgets, excels, emails) with the broad
    keyword rules produces false positives (e.g. an invoice mentioning
    "mesa" → ``foto_producto``). Use ``--all`` to force a full re-pass or
    ``--type <tipo>`` to target one specific type (e.g. scanned docs saved
    as images that were never categorized).
    """
    db = next(get_db())
    try:
        learned_rules = get_learned_rules(db)
        logger.info("Loaded %d learned rules", len(learned_rules))

        stmt = select(Document).where(Document.deleted_at.is_(None))
        if doc_type:
            stmt = stmt.where(Document.document_type == doc_type)
        elif only_unknown:
            stmt = stmt.where(Document.document_type == "desconocido")
        documents = list(db.scalars(stmt).all())
        logger.info("Found %d documents to reclassify", len(documents))

        changes = []
        errors = 0
        unchanged = 0

        for doc in documents:
            try:
                # Get the OCR text from the document's pages
                text = ""
                if hasattr(doc, "pages") and doc.pages:
                    text = "\n".join(
                        filter(None, (p.text for p in doc.pages if p.text))
                    )

                old_type = doc.document_type or "desconocido"
                result = classify_document(
                    filename=doc.original_filename,
                    source_path=doc.source_path,
                    text=text,
                    learned_rules=learned_rules,
                )

                new_type = result.document_type
                if new_type != old_type:
                    changes.append({
                        "id": doc.id,
                        "filename": doc.original_filename,
                        "old_type": old_type,
                        "new_type": new_type,
                        "confidence": result.confidence,
                        "rules": result.matched_rules,
                    })
                    if not dry_run:
                        doc.document_type = new_type
                        doc.confidence = result.confidence
                else:
                    unchanged += 1

                if verbose and new_type != old_type:
                    logger.info(
                        "  #%d %s: %s → %s (%.2f) %s",
                        doc.id,
                        doc.original_filename[:40],
                        old_type,
                        new_type,
                        result.confidence,
                        result.matched_rules,
                    )

            except Exception as exc:
                errors += 1
                logger.error("  Error on doc #%d: %s", doc.id, exc)

        if not dry_run and changes:
            db.commit()
            logger.info("Committed %d classification changes", len(changes))

        return {
            "total": len(documents),
            "changed": len(changes),
            "unchanged": unchanged,
            "errors": errors,
            "changes": changes[:50],  # First 50 for display
        }

    except Exception as exc:
        db.rollback()
        logger.error("Reclassification failed: %s", exc)
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Reclassify documents")
    parser.add_argument("--dry-run", action="store_true", help="Don't save changes")
    parser.add_argument("--verbose", action="store_true", help="Show each change")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Reclassify ALL documents (not only 'desconocido'). Risk of false positives.",
    )
    parser.add_argument(
        "--type",
        default=None,
        help="Reclassify only documents of this document_type (e.g. 'imagen').",
    )
    args = parser.parse_args()

    result = reclassify_all(
        dry_run=args.dry_run,
        verbose=args.verbose,
        only_unknown=not args.all and args.type is None,
        doc_type=args.type,
    )

    print(f"\n{'='*60}")
    print(f"RECLASSIFICATION RESULTS")
    print(f"{'='*60}")
    print(f"Total documents:    {result['total']}")
    print(f"Changed:            {result['changed']}")
    print(f"Unchanged:          {result['unchanged']}")
    print(f"Errors:             {result['errors']}")

    if result["changes"]:
        print(f"\nFirst {min(50, len(result['changes']))} changes:")
        for c in result["changes"]:
            print(f"  #{c['id']} {c['filename'][:35]:35s} {c['old_type']:20s} → {c['new_type']:20s} ({c['confidence']:.2f})")

    if args.dry_run:
        print(f"\n[DRY RUN] No changes saved.")


if __name__ == "__main__":
    main()
