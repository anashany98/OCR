"""F0-02: Differential tests for document_access_predicate vs metadata_allows_scope.

Verifies that the SQL predicate (``document_access_predicate``) produces
exactly the same allow/deny decisions as the Python function
(``metadata_allows_scope``) across a matrix of scope × metadata
combinations.
"""
from __future__ import annotations

import os
from collections.abc import Generator

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("ADMIN_PASSWORD", "y" * 22)

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models import Document, DocumentAccessMetadata
from app.services.tenant_access import (
    AccessScope,
    document_access_predicate,
    metadata_allows_scope,
)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sf = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )
    Base.metadata.create_all(engine)
    session = sf()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _make_doc(session: Session, **overrides) -> Document:
    defaults = dict(
        original_filename="test.pdf",
        stored_filename="test.pdf",
        source_path="/test.pdf",
        file_hash="abc123",
        file_size=100,
        document_type="contrato",
    )
    defaults.update(overrides)
    doc = Document(**defaults)
    session.add(doc)
    session.flush()
    return doc


def _make_metadata(
    session: Session,
    doc: Document,
    *,
    chain_id=None,
    hotel_id=None,
    assignment_status="assigned",
    tags=None,
) -> DocumentAccessMetadata:
    meta = DocumentAccessMetadata(
        document_id=doc.id,
        chain_id=chain_id,
        hotel_id=hotel_id,
        assignment_status=assignment_status,
        tags_json=tags or [],
    )
    session.add(meta)
    session.flush()
    return meta


def _sql_predicate_matches(
    session: Session, meta: DocumentAccessMetadata, scope: AccessScope
) -> bool:
    """Execute the SQL predicate and return True if the metadata row passes."""
    pred = document_access_predicate(scope)
    if pred is None:
        return True  # admin — everything passes
    result = session.scalar(
        select(pred).select_from(DocumentAccessMetadata).where(
            DocumentAccessMetadata.id == meta.id
        )
    )
    return bool(result)


# ---------------------------------------------------------------------------
# Matrix tests: Python vs SQL for each scope × metadata combination
# ---------------------------------------------------------------------------


class TestDocumentAccessPredicateMatrix:
    """30-case matrix comparing Python metadata_allows_scope with
    SQL document_access_predicate.
    """

    # --- Admin scope ---------------------------------------------------
    def test_admin_always_allowed(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1", is_admin=True
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, assignment_status="quarantine")
        assert metadata_allows_scope(meta, scope) is True
        assert _sql_predicate_matches(db_session, meta, scope) is True

    def test_admin_no_metadata(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1", is_admin=True
        )
        assert metadata_allows_scope(None, scope) is True
        # Predicate returns None for admin, meaning "no filter"
        assert document_access_predicate(scope) is None

    # --- Empty scope (deny-by-default) ---------------------------------
    def test_empty_scope_no_metadata(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_unassigned_documents=False,
        )
        assert metadata_allows_scope(None, scope) is False

    def test_empty_scope_assigned_no_hotel(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_all_hotels=False,
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc)
        assert metadata_allows_scope(meta, scope) is False
        assert _sql_predicate_matches(db_session, meta, scope) is False

    # --- allow_all_hotels ----------------------------------------------
    def test_allow_all_hotels_assigned(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_all_hotels=True,
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc)
        assert metadata_allows_scope(meta, scope) is True
        assert _sql_predicate_matches(db_session, meta, scope) is True

    def test_allow_all_hotels_quarantine_denied(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_all_hotels=True,
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, assignment_status="quarantine")
        assert metadata_allows_scope(meta, scope) is False
        assert _sql_predicate_matches(db_session, meta, scope) is False

    def test_allow_all_hotels_quarantine_allowed(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_all_hotels=True,
            allow_unassigned_documents=True,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, assignment_status="quarantine")
        assert metadata_allows_scope(meta, scope) is True
        assert _sql_predicate_matches(db_session, meta, scope) is True

    def test_allow_all_hotels_unassigned_no_metadata(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_all_hotels=True,
            allow_unassigned_documents=True,
        )
        assert metadata_allows_scope(None, scope) is True

    def test_allow_all_hotels_unassigned_denied_no_metadata(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_all_hotels=True,
            allow_unassigned_documents=False,
        )
        assert metadata_allows_scope(None, scope) is False

    # --- Hotel-level access --------------------------------------------
    def test_hotel_id_match(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            hotel_ids={10},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, hotel_id=10)
        assert metadata_allows_scope(meta, scope) is True
        assert _sql_predicate_matches(db_session, meta, scope) is True

    def test_hotel_id_no_match(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            hotel_ids={10},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, hotel_id=20)
        assert metadata_allows_scope(meta, scope) is False
        assert _sql_predicate_matches(db_session, meta, scope) is False

    def test_hotel_id_match_alongside_nonmatch(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            hotel_ids={10, 30},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, hotel_id=20)
        assert metadata_allows_scope(meta, scope) is False
        assert _sql_predicate_matches(db_session, meta, scope) is False

    # --- Chain-level access --------------------------------------------
    def test_chain_id_match(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            chain_ids={5},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, chain_id=5)
        assert metadata_allows_scope(meta, scope) is True
        assert _sql_predicate_matches(db_session, meta, scope) is True

    def test_chain_id_no_match(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            chain_ids={5},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, chain_id=99)
        assert metadata_allows_scope(meta, scope) is False
        assert _sql_predicate_matches(db_session, meta, scope) is False

    def test_chain_match_hotel_mismatch(self, db_session):
        """Chain matches but hotel doesn't — should still allow (chain covers it)."""
        scope = AccessScope(
            principal_type="user", principal_id="1",
            chain_ids={5},
            hotel_ids={99},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, chain_id=5, hotel_id=10)
        assert metadata_allows_scope(meta, scope) is True
        assert _sql_predicate_matches(db_session, meta, scope) is True

    # --- Denied tags ---------------------------------------------------
    def test_denied_tag_blocks(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_all_hotels=True,
            denied_tags={"contabilidad"},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, tags=["contabilidad"])
        assert metadata_allows_scope(meta, scope) is False
        assert _sql_predicate_matches(db_session, meta, scope) is False

    def test_denied_tag_no_overlap(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_all_hotels=True,
            denied_tags={"contabilidad"},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, tags=["legal"])
        assert metadata_allows_scope(meta, scope) is True
        assert _sql_predicate_matches(db_session, meta, scope) is True

    def test_denied_tag_empty_tags(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_all_hotels=True,
            denied_tags={"contabilidad"},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, tags=[])
        assert metadata_allows_scope(meta, scope) is True
        assert _sql_predicate_matches(db_session, meta, scope) is True

    def test_multiple_denied_tags_one_matches(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_all_hotels=True,
            denied_tags={"contabilidad", "rrhh"},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, tags=["rrhh"])
        assert metadata_allows_scope(meta, scope) is False
        assert _sql_predicate_matches(db_session, meta, scope) is False

    def test_tag_case_insensitive(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_all_hotels=True,
            denied_tags={"contabilidad"},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, tags=["CONTABILIDAD"])
        assert metadata_allows_scope(meta, scope) is False
        assert _sql_predicate_matches(db_session, meta, scope) is False

    # --- Unassigned / quarantine status --------------------------------
    def test_unassigned_quarantine_denied(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_all_hotels=True,
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, assignment_status="quarantine")
        assert metadata_allows_scope(meta, scope) is False
        assert _sql_predicate_matches(db_session, meta, scope) is False

    def test_unassigned_quarantine_allowed(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_all_hotels=True,
            allow_unassigned_documents=True,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, assignment_status="quarantine")
        assert metadata_allows_scope(meta, scope) is True
        assert _sql_predicate_matches(db_session, meta, scope) is True

    def test_unassigned_no_metadata_denied(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_unassigned_documents=False,
        )
        assert metadata_allows_scope(None, scope) is False

    def test_unassigned_no_metadata_allowed(self, db_session):
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_unassigned_documents=True,
        )
        assert metadata_allows_scope(None, scope) is True

    # --- Combined conditions -------------------------------------------
    def test_hotel_match_but_tag_denied(self, db_session):
        """Location matches but a denied tag blocks access."""
        scope = AccessScope(
            principal_type="user", principal_id="1",
            hotel_ids={10},
            denied_tags={"secret"},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, hotel_id=10, tags=["secret"])
        assert metadata_allows_scope(meta, scope) is False
        assert _sql_predicate_matches(db_session, meta, scope) is False

    def test_hotel_match_no_denied_tags(self, db_session):
        """Location matches and no tag overlap — allowed."""
        scope = AccessScope(
            principal_type="user", principal_id="1",
            hotel_ids={10},
            denied_tags={"secret"},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, hotel_id=10, tags=["legal"])
        assert metadata_allows_scope(meta, scope) is True
        assert _sql_predicate_matches(db_session, meta, scope) is True

    def test_quarantine_plus_hotel_match_denied(self, db_session):
        """Quarantine status denies even when hotel matches."""
        scope = AccessScope(
            principal_type="user", principal_id="1",
            hotel_ids={10},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(
            db_session, doc, hotel_id=10, assignment_status="quarantine"
        )
        assert metadata_allows_scope(meta, scope) is False
        assert _sql_predicate_matches(db_session, meta, scope) is False

    def test_quarantine_plus_hotel_match_allowed(self, db_session):
        """Quarantine allowed and hotel matches."""
        scope = AccessScope(
            principal_type="user", principal_id="1",
            hotel_ids={10},
            allow_unassigned_documents=True,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(
            db_session, doc, hotel_id=10, assignment_status="quarantine"
        )
        assert metadata_allows_scope(meta, scope) is True
        assert _sql_predicate_matches(db_session, meta, scope) is True

    # --- Edge cases ----------------------------------------------------
    def test_no_location_scope_empty(self, db_session):
        """No location IDs, no allow_all, quarantine denied → always deny."""
        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc)
        assert metadata_allows_scope(meta, scope) is False
        assert _sql_predicate_matches(db_session, meta, scope) is False

    def test_empty_scope_with_hotel_id_no_location_match(self, db_session):
        """Scope has hotel_ids but document has no hotel assigned."""
        scope = AccessScope(
            principal_type="user", principal_id="1",
            hotel_ids={10},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, hotel_id=None, chain_id=None)
        assert metadata_allows_scope(meta, scope) is False
        assert _sql_predicate_matches(db_session, meta, scope) is False

    def test_no_location_scope_no_hotel_on_doc(self, db_session):
        """Scope with hotel_ids but doc has no hotel → denied."""
        scope = AccessScope(
            principal_type="user", principal_id="1",
            hotel_ids={10, 20},
            allow_unassigned_documents=False,
        )
        doc = _make_doc(db_session)
        meta = _make_metadata(db_session, doc, hotel_id=None)
        assert metadata_allows_scope(meta, scope) is False
        assert _sql_predicate_matches(db_session, meta, scope) is False


# ---------------------------------------------------------------------------
# apply_access_predicates integration
# ---------------------------------------------------------------------------


class TestApplyAccessPredicatesIntegration:
    """Verify apply_access_predicates with the new predicate
    returns correct rows from a Document query.
    """

    def test_empty_scope_returns_no_documents(self, db_session):
        from app.services.tenant_access import apply_access_predicates

        doc = _make_doc(db_session)
        _make_metadata(db_session, doc)
        db_session.commit()

        scope = AccessScope(
            principal_type="user", principal_id="1",
            allow_unassigned_documents=False,
        )
        stmt = select(Document).where(Document.deleted_at.is_(None))
        rows = list(db_session.scalars(apply_access_predicates(stmt, scope)).all())
        assert rows == []

    def test_admin_returns_all_documents(self, db_session):
        from app.services.tenant_access import apply_access_predicates

        doc = _make_doc(db_session)
        _make_metadata(db_session, doc)
        db_session.commit()

        scope = AccessScope(
            principal_type="user", principal_id="1", is_admin=True,
        )
        stmt = select(Document).where(Document.deleted_at.is_(None))
        rows = list(db_session.scalars(apply_access_predicates(stmt, scope)).all())
        assert len(rows) == 1

    def test_hotel_scope_filters_correctly(self, db_session):
        from app.services.tenant_access import apply_access_predicates

        doc_a = _make_doc(db_session, original_filename="a.pdf", file_hash="a1")
        _make_metadata(db_session, doc_a, hotel_id=10)
        doc_b = _make_doc(db_session, original_filename="b.pdf", file_hash="b2")
        _make_metadata(db_session, doc_b, hotel_id=20)
        db_session.commit()

        scope = AccessScope(
            principal_type="user", principal_id="1",
            hotel_ids={10},
            allow_unassigned_documents=False,
        )
        stmt = select(Document).where(Document.deleted_at.is_(None))
        rows = list(db_session.scalars(apply_access_predicates(stmt, scope)).all())
        assert len(rows) == 1
        assert rows[0].id == doc_a.id
