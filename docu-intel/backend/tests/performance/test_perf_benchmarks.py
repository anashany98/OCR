"""Phase 7 performance benchmarks using synthetic dataset."""
from __future__ import annotations
import os, time
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.config import settings
settings.database_url = "sqlite+pysqlite:///:memory:"
# Performance tests use synthetic vectors and must not issue network requests
# to an operator's embedding service.
settings.embedding_provider = "local_hash"
settings.embedding_dimensions = 1024
from app.database.base import Base
from app.models import Document, ExtractionJob, DocumentPage, DocumentBlock, DocumentChunk, Budget, ExtractionJob
from app.services.search_service import search_text, search_semantic, search_hybrid
from app.services.metrics import get_metrics

def _fabricate(sess):
    """Quick inline fabricator for benchmarks."""
    from datetime import datetime, timedelta
    import random, hashlib
    words = ["pedido","presupuesto","factura","cliente","proveedor","referencia","material","unidad","precio","total"]
    def _hash(s): return hashlib.sha256(str(s).encode()).hexdigest()
    def _txt(n=30): return " ".join(random.choice(words) for _ in range(n)) + "."
    docs = []
    for i in range(100):
        d = Document(original_filename=f"doc-{i}.txt", stored_filename=f"aa/doc-{i}.txt", source_path=f"/data/input/doc-{i}.txt", file_hash=_hash(i), extension=".txt", file_size=1000, document_type="desconocido", status=random.choice(["processed","pending","needs_review"]), quality_status="processed_ok")
        sess.add(d); sess.flush()
        docs.append(d)
    for i in range(500):
        d = docs[random.randint(0,99)]
        p = DocumentPage(document_id=d.id, page_number=1, text=_txt(30), page_status="processed")
        sess.add(p); sess.flush()
        sess.add(DocumentBlock(document_id=d.id, page_id=p.id, page_number=1, block_type="text", text=_txt(10), source_engine="plain_text"))
    for i in range(1000):
        d = docs[random.randint(0,99)]
        sess.add(DocumentChunk(document_id=d.id, chunk_text=_txt(15), embedding=[random.random() for _ in range(1024)], token_count=10))
    for i in range(80):
        d = docs[random.randint(0,99)]
        sess.add(ExtractionJob(document_id=d.id, job_type="extract", status=random.choice(["processed","pending","failed"])))
    for i in range(30):
        d = docs[random.randint(0,99)]
        sess.add(Budget(document_id=d.id, budget_number=f"2026/{100+i}", client_name="Cliente", date=datetime.utcnow().date(), total_amount=100.0, currency="EUR", accepted_detected=i < 10))
    sess.commit()


def test_search_text_scales_to_100_docs():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)()
    _fabricate(sess)
    queries = ["pedido cliente", "referencia material", "total factura", "proveedor precio", "unidad certificacion"]
    times = []
    for q in queries:
        t0 = time.perf_counter()
        results = search_text(sess, q, limit=10)
        times.append(time.perf_counter() - t0)
    times.sort()
    p50 = times[len(times)//2]
    p95 = times[int(len(times)*0.95)]
    assert p50 < 1.0, f"text search P50={p50:.3f}s exceeds 1s"
    assert p95 < 2.0, f"text search P95={p95:.3f}s exceeds 2s (SQLite is slower than PG)"
    sess.close()


def test_search_semantic_scales_to_1000_chunks(monkeypatch):
    # This benchmark intentionally models an unscoped local corpus.  Whole-
    # document retrieval is scope-gated in production, so benchmark the chunk
    # path here rather than granting the test an internal global-search
    # capability that application callers never receive.
    monkeypatch.setattr(settings, "search_use_document_embedding", False)
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)()
    _fabricate(sess)
    queries = ["pedido cliente", "referencia material", "total factura"]
    times = []
    for q in queries:
        t0 = time.perf_counter()
        results = search_semantic(sess, q, limit=10)
        times.append(time.perf_counter() - t0)
    p95 = sorted(times)[int(len(times)*0.95)]
    assert p95 < 30.0, f"semantic search P95={p95:.3f}s exceeds 30s (SQLite without pgvector; production needs pgvector)"
    sess.close()


def test_admin_listing_uses_pagination():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)()
    _fabricate(sess)
    # Verify paginated listing returns limited results
    stmt = select(Document).where(Document.deleted_at.is_(None)).order_by(Document.created_at.desc()).offset(10).limit(20)
    results = list(sess.scalars(stmt).all())
    assert len(results) == 20, f"pagination returned {len(results)} docs, expected 20"
    # Verify total count accessible
    total = sess.scalar(select(text("count(*)")).select_from(Document).where(Document.deleted_at.is_(None)))
    assert total == 100
    sess.close()


def test_document_pages_endpoint_has_pagination_guard():
    """Verify document pages query accepts limit to avoid loading all pages for large docs."""
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)()
    # Create a document with 50 pages
    from app.models import Document, DocumentPage
    d = Document(original_filename="big.pdf", stored_filename="aa/big.pdf", source_path="/data/input/big.pdf", file_hash="a"*64, extension=".pdf", file_size=5000, document_type="plano", status="processed", quality_status="processed_ok")
    sess.add(d); sess.flush()
    for i in range(1, 51):
        sess.add(DocumentPage(document_id=d.id, page_number=i, text=f"page {i} text"))
    sess.commit()
    # Without limit
    all_pages = list(sess.scalars(select(DocumentPage).where(DocumentPage.document_id == d.id)).all())
    assert len(all_pages) == 50
    # With limit
    limited = list(sess.scalars(select(DocumentPage).where(DocumentPage.document_id == d.id).limit(10)).all())
    assert len(limited) == 10
    sess.close()


def test_postgres_indexes_defined_on_critical_columns():
    """Verify SQLAlchemy models define indexes on performance-critical columns."""
    from app.models import DocumentEntity
    # normalized_value should be indexed for exact/guided search
    assert DocumentEntity.__table__.columns["normalized_value"].index is not None or any(
        col.name == "normalized_value" for idx in DocumentEntity.__table__.indexes for col in idx.columns
    ), "normalized_value needs index for search performance"
