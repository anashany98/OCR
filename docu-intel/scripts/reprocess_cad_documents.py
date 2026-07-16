"""Queue a bounded, non-destructive CAD reprocess.

Only documents explicitly selected by ``--document-id`` or the extension
filter are touched. ``--dry-run`` is the default safety check.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.models import Document  # noqa: E402
from app.services.document_reprocess_service import reprocess_document  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="enqueue the selected documents; without this option the script only reports them",
    )
    parser.add_argument(
        "--dry-run",
        dest="apply",
        action="store_false",
        help="compatibility alias; dry-run is already the default",
    )
    parser.add_argument("--document-id", action="append", type=int, default=[])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=5)
    args = parser.parse_args()
    if args.limit < 1 or args.batch_size < 1:
        parser.error("--limit and --batch-size must be positive")
    with SessionLocal() as db:
        stmt = select(Document).where(Document.deleted_at.is_(None)).where(
            Document.extension.in_([".dxf", ".dwg"])
        ).order_by(Document.id.asc()).limit(args.limit)
        if args.document_id:
            stmt = select(Document).where(Document.id.in_(args.document_id)).where(Document.deleted_at.is_(None))
        documents = list(db.scalars(stmt).all())
        report = {"dry_run": not args.apply, "selected": [doc.id for doc in documents], "queued": []}
        if args.apply:
            for offset in range(0, len(documents), args.batch_size):
                for document in documents[offset : offset + args.batch_size]:
                    job = reprocess_document(db, document=document, user=None, enqueue=True, job_type="reprocess")
                    report["queued"].append({"document_id": document.id, "job_id": job.id})
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
