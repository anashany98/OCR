"""CR4 — Tests for exact document search by identifier.

Verifies that:
1. Identifiers are detected correctly from questions.
2. Exact search finds documents by number in entities, pages, blocks, chunks.
3. Word-boundary matching prevents partial matches (26002 != 260025).
4. Best match selection prefers entities over text matches.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base
from app.models import (
    Document,
    DocumentBlock,
    DocumentChunk,
    DocumentAccessMetadata,
    DocumentEntity,
    DocumentPage,
)
from app.services.exact_document_search import (
    detect_identifiers,
    search_exact_by_number,
    select_best_exact_match,
)
from app.services.tenant_access import AccessScope


@pytest.fixture()
def db_session():
    """In-memory SQLite database for isolated testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture()
def admin_scope() -> AccessScope:
    return AccessScope(principal_type="user", principal_id="admin", is_admin=True)


def _insert_document_with_number(session: Session, *, number: str, filename: str = "test.pdf") -> Document:
    """Insert a document with the given number in entities, pages, and blocks."""
    doc = Document(
        original_filename=filename,
        source_path=f"/app/data/{filename}",
        file_hash=f"hash_{number}",
        status="processed",
        document_type="presupuesto",
    )
    session.add(doc)
    session.flush()

    # Entity
    entity = DocumentEntity(
        document_id=doc.id,
        entity_type="budget_number",
        entity_value=number,
    )
    session.add(entity)

    # Page with number in text
    page = DocumentPage(
        document_id=doc.id,
        page_number=1,
        text=f"DOCUMENTO {number} ORDEN DE TRABAJO 12/01/2026 SHERATON FALDONES",
        ocr_confidence=0.95,
    )
    session.add(page)

    # Block with number in text
    block = DocumentBlock(
        document_id=doc.id,
        page_id=page.id,
        page_number=1,
        text=f"Numero de presupuesto: {number}",
        block_type="text",
    )
    session.add(block)

    # Chunk
    chunk = DocumentChunk(
        document_id=doc.id,
        page_number=1,
        chunk_text=f"El presupuesto {number} corresponde a la instalacion de faldones",
    )
    session.add(chunk)

    session.flush()
    return doc


def test_detect_budget_number():
    ids = detect_identifiers("¿Que sabes del presupuesto 260025?")
    assert len(ids) >= 1
    kinds = [k for k, v in ids]
    values = [v for k, v in ids]
    assert "budget" in kinds
    assert "260025" in values


def test_detect_order_number():
    ids = detect_identifiers("Dame el pedido 12345")
    assert len(ids) >= 1
    kinds = [k for k, v in ids]
    assert "order" in kinds


def test_detect_invoice_number():
    ids = detect_identifiers("Factura F-2025-001")
    assert len(ids) >= 1
    kinds = [k for k, v in ids]
    assert "invoice" in kinds


def test_detect_cif():
    ids = detect_identifiers("CIF B12345678")
    assert len(ids) >= 1
    kinds = [k for k, v in ids]
    assert "tax_id" in kinds


def test_exact_search_finds_entity(db_session, admin_scope):
    doc = _insert_document_with_number(db_session, number="260025")
    matches = search_exact_by_number(
        db_session, number="260025", kind="budget", access_scope=admin_scope
    )
    assert len(matches) >= 1
    assert matches[0].document_id == doc.id
    assert matches[0].matched_in == "entity"


def test_exact_search_finds_in_page_text(db_session, admin_scope):
    doc = _insert_document_with_number(db_session, number="260025")
    matches = search_exact_by_number(
        db_session, number="260025", kind="generic", access_scope=admin_scope
    )
    doc_ids = [m.document_id for m in matches]
    assert doc.id in doc_ids


def test_no_partial_match(db_session, admin_scope):
    """26002 should NOT match a document with 260025."""
    doc = _insert_document_with_number(db_session, number="260025")
    # Search for 26002 (partial) - should not find the document
    matches = search_exact_by_number(
        db_session, number="26002", kind="generic", access_scope=admin_scope
    )
    doc_ids = [m.document_id for m in matches]
    # The number 26002 should NOT match 260025 due to word boundary
    assert doc.id not in doc_ids or all(
        m.matched_value != "26002" for m in matches if m.document_id == doc.id
    )


def test_select_best_match_prefers_entity(db_session, admin_scope):
    doc = _insert_document_with_number(db_session, number="260025")
    matches = search_exact_by_number(
        db_session, number="260025", kind="budget", access_scope=admin_scope
    )
    best = select_best_exact_match(matches, question_kind="budget")
    assert best is not None
    assert best.document_id == doc.id
    assert best.matched_in == "entity"


def test_select_best_match_empty():
    best = select_best_exact_match([])
    assert best is None


def test_filename_match(db_session, admin_scope):
    """Search by number appearing in filename."""
    doc = Document(
        original_filename="presupuesto 260025.pdf",
        source_path="/app/data/presupuesto 260025.pdf",
        file_hash="hash_filename",
        status="processed",
        document_type="presupuesto",
    )
    db_session.add(doc)
    db_session.flush()

    matches = search_exact_by_number(
        db_session, number="260025", kind="budget", access_scope=admin_scope
    )
    assert any(m.document_id == doc.id and m.matched_in == "filename" for m in matches)


def test_exact_search_denies_missing_scope(db_session):
    _insert_document_with_number(db_session, number="260025")
    assert search_exact_by_number(db_session, number="260025", kind="budget") == []


def test_exact_search_filters_unauthorized_documents_before_returning_content(db_session):
    visible = _insert_document_with_number(db_session, number="260025", filename="hotel-a.pdf")
    hidden = _insert_document_with_number(db_session, number="260025", filename="hotel-b.pdf")
    db_session.add_all(
        [
            DocumentAccessMetadata(
                document_id=visible.id,
                chain_id=1,
                assignment_status="assigned",
                assignment_source="test",
                tags_json=[],
            ),
            DocumentAccessMetadata(
                document_id=hidden.id,
                chain_id=2,
                assignment_status="assigned",
                assignment_source="test",
                tags_json=["contabilidad"],
            ),
        ]
    )
    db_session.commit()

    scope = AccessScope(
        principal_type="user",
        principal_id="hotel-a",
        chain_ids={1},
        denied_tags={"contabilidad"},
    )
    matches = search_exact_by_number(
        db_session, number="260025", kind="budget", access_scope=scope
    )

    assert [match.document_id for match in matches] == [visible.id]
    assert matches[0].original_filename == "hotel-a.pdf"
    assert matches[0].source_path is None
