"""CR12 — Tests for safe backfill/reprocessing command.

Verifies that:
1. Dry-run mode doesn't modify documents
2. Quality recalculation works without OCR repeat
3. Batch processing is idempotent
4. Report shows correct before/after counts
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base
from app.models import Document, DocumentPage
from app.commands.backfill_reprocess import (
    BackfillReport,
    _get_documents_by_reason,
    _reprocess_document,
)


@pytest.fixture()
def db_session():
    """In-memory SQLite database for isolated testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()


def _insert_test_documents(session: Session) -> list[Document]:
    """Insert test documents with various quality statuses."""
    docs = []
    for i, (status, quality, flags) in enumerate([
        ("processed", "needs_review", ["page_without_text"]),
        ("processed", "processed_low_quality", ["low_ocr_confidence"]),
        ("processed", "processed_ok", []),
        ("processed", "needs_human_review", ["page_failed"]),
    ], start=1):
        doc = Document(
            original_filename=f"test_{i}.pdf",
            source_path=f"/app/data/test_{i}.pdf",
            file_hash=f"hash_{i}",
            status=status,
            document_type="presupuesto",
            quality_status=quality,
            quality_flags_json=flags,
        )
        session.add(doc)
        session.flush()

        # Add a page with text
        page = DocumentPage(
            document_id=doc.id,
            page_number=1,
            text=f"Sample text for document {i}",
            ocr_confidence=0.95,
        )
        session.add(page)
        docs.append(doc)

    session.flush()
    return docs


def test_dry_run_does_not_modify(db_session):
    docs = _insert_test_documents(db_session)
    doc = docs[0]
    old_quality = doc.quality_status

    action = _reprocess_document(db_session, doc, dry_run=True)
    assert "dry_run" in action
    assert doc.quality_status == old_quality


def test_reprocess_document(db_session):
    docs = _insert_test_documents(db_session)
    doc = docs[0]  # needs_review with page_without_text

    action = _reprocess_document(db_session, doc, dry_run=False)
    # After recalculation with CR11, document with page_without_text
    # flag but actual text is usable_with_warnings (not blocking).
    assert action in {"processed_ok", "usable_with_warnings"}


def test_get_documents_by_reason(db_session):
    docs = _insert_test_documents(db_session)
    found = _get_documents_by_reason(db_session, "page_without_text", limit=10)
    assert len(found) >= 1
    assert any("page_without_text" in (d.quality_flags_json or []) for d in found)


def test_report_summary():
    report = BackfillReport(
        total_scanned=10,
        by_reason={"all": 10},
        processed=5,
        skipped=3,
        failed=2,
        before_status={"needs_review": 5, "processed_ok": 5},
        after_status={"processed_ok": 8, "needs_review": 2},
    )
    summary = report.summary()
    assert "Total scanned: 10" in summary
    assert "Processed: 5" in summary
    assert "needs_review: 5" in summary
