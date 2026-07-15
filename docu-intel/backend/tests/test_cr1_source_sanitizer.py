"""CR1 — Tests for source sanitizer: stale block_id handling.

Verifies that:
1. Valid block_id is passed through unchanged.
2. Stale block_id is set to NULL and source is marked degraded.
3. block_id=None passes through unchanged.
4. Batch sanitizer works correctly.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base
from app.models import AIAnswerSource, Document, DocumentBlock, DocumentPage
from app.services.source_sanitizer import sanitize_sources_batch, sanitize_source_reference


@pytest.fixture()
def db_session():
    """In-memory SQLite database for isolated testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()


def _insert_test_document(session: Session) -> Document:
    """Insert a minimal Document + page + block for testing."""
    doc = Document(
        original_filename="test.pdf",
        source_path="/app/data/test.pdf",
        file_hash="abc123hash",
        status="processed",
        document_type="presupuesto",
    )
    session.add(doc)
    session.flush()
    page = DocumentPage(
        document_id=doc.id,
        page_number=1,
        text="Sample text for testing",
        ocr_confidence=0.95,
    )
    session.add(page)
    session.flush()
    block = DocumentBlock(
        document_id=doc.id,
        page_id=page.id,
        page_number=1,
        text="Sample block text",
        block_type="text",
    )
    session.add(block)
    session.flush()
    return doc


def test_valid_block_id_passthrough(db_session):
    doc = _insert_test_document(db_session)
    block = db_session.query(DocumentBlock).first()
    result = sanitize_source_reference(
        db_session,
        document_id=doc.id,
        page_number=1,
        block_id=block.id,
        relevance_score=0.9,
        excerpt="test excerpt",
    )
    assert result.block_id == block.id
    assert result.degraded is False
    assert result.document_id == doc.id


def test_stale_block_id_sets_none(db_session):
    doc = _insert_test_document(db_session)
    result = sanitize_source_reference(
        db_session,
        document_id=doc.id,
        page_number=1,
        block_id=99999,
        relevance_score=0.8,
        excerpt="stale block",
    )
    assert result.block_id is None
    assert result.degraded is True
    assert result.document_id == doc.id
    assert result.excerpt == "stale block"


def test_none_block_id_passthrough(db_session):
    result = sanitize_source_reference(
        db_session,
        document_id=1,
        page_number=1,
        block_id=None,
        relevance_score=0.7,
        excerpt="no block",
    )
    assert result.block_id is None
    assert result.degraded is False


def test_batch_sanitizer_mixed(db_session):
    doc = _insert_test_document(db_session)
    block = db_session.query(DocumentBlock).first()
    sources = [
        {
            "document_id": doc.id,
            "page_number": 1,
            "block_id": block.id,
            "relevance_score": 0.9,
            "excerpt": "valid",
        },
        {
            "document_id": doc.id,
            "page_number": 1,
            "block_id": 99999,
            "relevance_score": 0.8,
            "excerpt": "stale",
        },
        {
            "document_id": doc.id,
            "page_number": 1,
            "block_id": None,
            "relevance_score": 0.7,
            "excerpt": "no block",
        },
    ]
    results = sanitize_sources_batch(db_session, sources)
    assert len(results) == 3
    assert results[0].block_id == block.id
    assert results[0].degraded is False
    assert results[1].block_id is None
    assert results[1].degraded is True
    assert results[2].block_id is None
    assert results[2].degraded is False


def test_ai_answer_source_with_null_block_id(db_session):
    """Verify that AIAnswerSource can be created with block_id=NULL
    (the whole point of CR1 — preventing FK violations)."""
    doc = _insert_test_document(db_session)
    from app.models import AIAnswer, AIQuestion, User

    user = User(name="test", email="test@test.com", password_hash="x", role="admin")
    db_session.add(user)
    db_session.flush()
    question = AIQuestion(user_id=user.id, question="test question")
    db_session.add(question)
    db_session.flush()
    answer = AIAnswer(question_id=question.id, answer="test answer")
    db_session.add(answer)
    db_session.flush()
    source = AIAnswerSource(
        answer_id=answer.id,
        document_id=doc.id,
        page_number=1,
        block_id=None,  # CR1: this should NOT cause FK violation
        relevance_score=0.9,
        excerpt="test",
    )
    db_session.add(source)
    db_session.flush()
    assert source.block_id is None
    assert source.document_id == doc.id
