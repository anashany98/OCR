"""Fabricate benchmark dataset for Phase 7 performance testing.
Usage: python -m tests.performance.fabricate_benchmark_data [--scale 1]
Scale multiplies all counts (default 1 ~ 100 docs, 500 pages, 2000 chunks)."""
from __future__ import annotations
import argparse, hashlib, os, random, time
from datetime import datetime, timedelta
from pathlib import Path
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.config import settings
settings.database_url = "sqlite+pysqlite:///:memory:"
from app.database.base import Base
from app.models import (AuditLog, Budget, BudgetLine, Document, DocumentBlock, DocumentChunk, DocumentEntity, DocumentPage, ExtractionJob, Order, OrderLine, Plan, PlanDimension, PlanRoom, User, WatchedFile, IngestionEvent)

SPANISH_WORDS = ["pedido", "presupuesto", "factura", "cliente", "proveedor", "referencia", "material", "unidad", "precio", "total", "fecha", "entrega", "plano", "escala", "metros", "habitacion", "muro", "puerta", "ventana", "cocina", "bano", "salon", "dormitorio", "hotel", "obra", "contratista", "certificacion", "importe", "iva", "base"]

def _hash(seed): return hashlib.sha256(str(seed).encode()).hexdigest()
def _now(): return datetime.utcnow()
def _rand_date(days_back=365): return (_now() - timedelta(days=random.randint(0, days_back), hours=random.randint(0, 23))).replace(tzinfo=None)
def _rand_text(min_words=20, max_words=80):
    return " ".join(random.choice(SPANISH_WORDS) for _ in range(random.randint(min_words, max_words))).capitalize() + "."
def _rand_embedding(dim=8): return [random.random() for _ in range(dim)]

def fabricate(scale=1):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)()
    t0 = time.perf_counter()
    user = User(email="admin@local", name="Admin", password_hash="hash", role="admin", is_active=True)
    sess.add(user); sess.flush()
    
    n_docs = 100 * scale
    statuses = [("processed", 60), ("pending", 15), ("failed", 5), ("needs_review", 10), ("duplicate", 10)]
    exts = [((".pdf","plano"), 30), ((".xlsx","excel"), 20), ((".png","imagen"), 15), ((".txt","desconocido"), 20), ((".jpg","imagen"), 10), ((".csv","excel"), 5)]
    docs = []
    for i in range(n_docs):
        (ext, dtype), _ = random.choices(exts, weights=[w for _, w in exts])[0]
        status, _ = random.choices([s for s, _ in statuses], weights=[w for _, w in statuses])[0]
        proc = _rand_date() if status in ("processed","needs_review") else None
        d = Document(original_filename=f"doc-{i}{ext}", stored_filename=f"aa/doc-{i}{ext}", source_path=f"/data/input/doc-{i}{ext}", file_hash=_hash(i), mime_type="application/octet-stream", extension=ext, file_size=random.randint(1000, 500000), document_type=dtype, status=status, quality_status="processed_ok" if status == "processed" else ("needs_human_review" if status == "needs_review" else status), processed_at=proc)
        sess.add(d); sess.flush()
        docs.append(d)
    
    n_pages = 500 * scale
    for i in range(n_pages):
        d = docs[random.randint(0, len(docs)-1)]
        p = DocumentPage(document_id=d.id, page_number=random.randint(1, 5), text=_rand_text(10, 50), page_status="processed", ocr_confidence=random.uniform(0.5, 1.0))
        sess.add(p); sess.flush()
        for _ in range(random.randint(1, 5)):
            sess.add(DocumentBlock(document_id=d.id, page_id=p.id, page_number=p.page_number, block_type="text", text=_rand_text(5, 20), source_engine="plain_text"))
    
    n_chunks = 1000 * scale
    for i in range(n_chunks):
        d = docs[random.randint(0, len(docs)-1)]
        sess.add(DocumentChunk(document_id=d.id, page_number=random.randint(1, 5), chunk_text=_rand_text(10, 30), embedding=_rand_embedding(), token_count=random.randint(5, 50)))
    
    n_entities = 200 * scale
    for i in range(n_entities):
        d = docs[random.randint(0, len(docs)-1)]
        val = f"REF-{random.randint(100, 999)}"
        sess.add(DocumentEntity(document_id=d.id, entity_type=random.choice(["reference","budget_number","client_name"]), entity_value=val, normalized_value=val.lower()))
    
    n_jobs = 120 * scale
    for i in range(n_jobs):
        d = docs[random.randint(0, len(docs)-1)]
        sess.add(ExtractionJob(document_id=d.id, job_type="extract", status=random.choice(["processed","pending","failed","processing"]), retries=random.randint(0, 2)))
    
    n_budgets = 40 * scale
    for i in range(n_budgets):
        b = Budget(document_id=docs[random.randint(0, len(docs)-1)].id, budget_number=f"2026/{100+i}", client_name="Cliente Demo", date=_rand_date().date(), total_amount=random.uniform(100, 5000), currency="EUR", accepted_detected=random.random() < 0.3)
        sess.add(b); sess.flush()
        for _ in range(random.randint(1, 5)):
            sess.add(BudgetLine(budget_id=b.id, reference=f"REF-{random.randint(100,999)}", quantity=random.randint(1, 10), total_price=random.uniform(10, 500)))
    
    n_orders = 25 * scale
    for i in range(n_orders):
        o = Order(document_id=docs[random.randint(0, len(docs)-1)].id, order_number=f"P-{200+i}", supplier_name="Proveedor Demo", date=_rand_date().date(), total_amount=random.uniform(100, 5000), currency="EUR")
        sess.add(o); sess.flush()
        for _ in range(random.randint(1, 3)):
            sess.add(OrderLine(order_id=o.id, reference=f"REF-{random.randint(100,999)}", quantity=random.randint(1, 10), total_price=random.uniform(10, 500)))
    
    for _ in range(10 * scale):
        sess.add(Plan(document_id=docs[random.randint(0, len(docs)-1)].id, project_name="Proyecto Demo", has_valid_scale=random.random() > 0.3))
    
    for _ in range(200 * scale):
        sess.add(AuditLog(user_id=user.id, action=random.choice(["document_registered","document_processed","job_failed"]), entity_type="document", entity_id=random.randint(1, n_docs)))
    
    for _ in range(30 * scale):
        sess.add(WatchedFile(path=f"/data/input/doc-{random.randint(0, n_docs-1)}", status=random.choice(["registered","skipped","failed","pending"])))
    
    sess.commit()
    elapsed = time.perf_counter() - t0
    counts = {
        "documents": n_docs, "pages": n_pages, "chunks": n_chunks, "entities": n_entities,
        "jobs": n_jobs, "budgets": n_budgets, "orders": n_orders
    }
    print(f"Fabricated {scale}x benchmark dataset in {elapsed:.1f}s: {counts}")
    sess.close()
    return counts

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=int, default=1)
    args = parser.parse_args()
    fabricate(args.scale)
