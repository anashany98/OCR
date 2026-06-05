"""Tests for the ``GET /admin/documents/needs-re-embedding`` endpoint.

The endpoint returns one row per document that has at least one chunk
with ``needs_reembedding=True``, with the total chunk count and the
count of chunks that still need an embedding. We exercise the SQL
aggregation against an in-memory SQLite DB.
"""
from __future__ import annotations

from app.services import document_service  # noqa: F401  (facade lookup)
from unittest.mock import patch

import pytest


def _make_document_with_chunks(
    db,
    *,
    filename: str,
    n_total: int,
    n_needing: int,
    doc_type: str = "invoice",
    status: str = "processed",
) -> int:
    """Create a Document + N DocumentChunks, M of which have
    ``needs_reembedding=True``."""
    from app.models import Document, DocumentChunk

    assert 0 <= n_needing <= n_total
    document = Document(
        original_filename=filename,
        stored_filename=f"aa/{filename}",
        source_path=f"/data/input/{filename}",
        file_hash=hashlib_for(filename),
        mime_type="application/pdf",
        extension=".pdf",
        file_size=1024,
        document_type=doc_type,
        status=status,
    )
    db.add(document)
    db.flush()
    for i in range(n_total):
        db.add(
            DocumentChunk(
                document_id=document.id,
                page_number=1,
                chunk_text=f"chunk {i}",
                embedding=None if i < n_needing else [0.0] * 1024,
                needs_reembedding=(i < n_needing),
                token_count=2,
            )
        )
    db.commit()
    return document.id


def hashlib_for(name: str) -> str:
    import hashlib

    return hashlib.md5(name.encode()).hexdigest()


def test_endpoint_returns_only_documents_with_needing_chunks():
    from app.database.base import Base
    from fastapi.testclient import TestClient

    from app.api.deps import require_roles
    from app.core.security import create_access_token, hash_password
    from app.database.session import get_db
    from app.main import app
    from app.models import User

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Seed: admin user, 3 documents (1 fully embedded, 1 partial, 1 full fail).
    with Session() as db:
        _make_document_with_chunks(db, filename="clean.pdf", n_total=4, n_needing=0)
        _make_document_with_chunks(db, filename="partial.pdf", n_total=10, n_needing=3)
        _make_document_with_chunks(db, filename="broken.pdf", n_total=5, n_needing=5)

        admin = User(
            email="admin@local", name="Admin",
            password_hash=hash_password("secret"), role="admin", is_active=True,
        )
        db.add(admin)
        db.commit()
        token = create_access_token(str(admin.id))

    client = TestClient(app)
    response = client.get(
        "/api/v1/admin/documents/needs-re-embedding",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    items = response.json()
    # The fully-embedded document is excluded.
    filenames = {item["original_filename"] for item in items}
    assert "clean.pdf" not in filenames
    assert "partial.pdf" in filenames
    assert "broken.pdf" in filenames

    by_name = {item["original_filename"]: item for item in items}
    assert by_name["partial.pdf"]["chunks_total"] == 10
    assert by_name["partial.pdf"]["chunks_needing_reembedding"] == 3
    assert by_name["broken.pdf"]["chunks_total"] == 5
    assert by_name["broken.pdf"]["chunks_needing_reembedding"] == 5


def test_endpoint_respects_limit():
    from app.database.base import Base
    from fastapi.testclient import TestClient

    from app.core.security import create_access_token, hash_password
    from app.database.session import get_db
    from app.main import app
    from app.models import User

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Session = _session_factory(engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with Session() as db:
        for i in range(5):
            _make_document_with_chunks(db, filename=f"doc{i}.pdf", n_total=2, n_needing=2)
        admin = User(
            email="admin@local", name="Admin",
            password_hash=hash_password("secret"), role="admin", is_active=True,
        )
        db.add(admin)
        db.commit()
        token = create_access_token(str(admin.id))

    client = TestClient(app)
    response = client.get(
        "/api/v1/admin/documents/needs-re-embedding?limit=2",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_endpoint_requires_auth():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.get("/api/v1/admin/documents/needs-re-embedding")
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _memory_engine():
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _session_factory(engine):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
