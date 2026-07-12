from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.database.base import Base
from app.models import Document, ExtractionJob, User
from app.services import document_service
from app.services.queue_control import build_queue_control_status, cancel_pending_job
from app.services.document_service import mode_requires_file_parse, prepare_document_chunks, processing_mode_from_job_type
from app.services.operations import ALERT_DEFINITIONS, BulkReprocessFilters, bulk_reprocess_documents, normalize_bulk_reprocess_filters


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _document(db: Session, filename: str, *, status: str = "processed", quality_status: str = "processed_ok") -> Document:
    document = Document(
        original_filename=filename,
        stored_filename=f"aa/{filename}",
        source_path=f"/data/input/{filename}",
        file_hash=(filename.replace(".", "")[:1] or "a") * 64,
        mime_type="application/octet-stream",
        extension=Path(filename).suffix.lower(),
        file_size=10,
        document_type="plano" if Path(filename).suffix.lower() in {".pdf", ".png", ".jpg"} else "excel",
        status=status,
        quality_status=quality_status,
        processed_at=datetime.utcnow() if status in {"processed", "needs_review"} else None,
    )
    db.add(document)
    db.flush()
    return document


def _user(db: Session) -> User:
    user = User(email="admin@local", name="Admin", password_hash="hash", role="admin", is_active=True)
    db.add(user)
    db.flush()
    return user


def test_bulk_reprocess_filters_clamp_limit_and_require_a_selector():
    filters = normalize_bulk_reprocess_filters(BulkReprocessFilters(status="failed", limit=1000))

    assert filters.status == "failed"
    assert filters.limit == 200


def test_bulk_reprocess_filters_reject_unbounded_request():
    try:
        normalize_bulk_reprocess_filters(BulkReprocessFilters())
    except ValueError as exc:
        assert "at least one selector" in str(exc)
    else:
        raise AssertionError("unbounded bulk reprocess request should fail")


def test_alert_definitions_cover_phase5_operational_risks():
    keys = {definition.key for definition in ALERT_DEFINITIONS}

    assert {
        "accepted_budgets_without_order",
        "orders_without_budget",
        "ocr_review_documents",
        "plans_without_valid_scale",
        "duplicate_documents",
        "failed_jobs",
    }.issubset(keys)


def test_processing_mode_from_job_type_maps_partial_reprocess_modes():
    assert processing_mode_from_job_type("extract") == "full"
    assert processing_mode_from_job_type("reprocess") == "full"
    assert processing_mode_from_job_type("reprocess:full") == "full"
    assert processing_mode_from_job_type("reprocess:ocr") == "ocr"
    assert processing_mode_from_job_type("reprocess:ocr_page:3") == "ocr_page"
    assert processing_mode_from_job_type("reprocess:classification") == "classification"
    assert processing_mode_from_job_type("reprocess:embeddings") == "embeddings"


def test_partial_reprocess_modes_skip_file_parse():
    assert mode_requires_file_parse("full") is True
    assert mode_requires_file_parse("ocr") is True
    assert mode_requires_file_parse("classification") is False
    assert mode_requires_file_parse("embeddings") is False


def test_prepare_document_chunks_can_rebuild_from_existing_page_text(monkeypatch):
    calls: list[list[str]] = []

    def fake_embed_many(texts):
        calls.append(list(texts))
        return [[0.1] * 1024 for _ in texts]

    monkeypatch.setattr(document_service, "should_create_embeddings", lambda: True)
    monkeypatch.setattr(
        "app.services.document_embedding_pipeline.embed_many", fake_embed_many
    )

    chunks = prepare_document_chunks(
        document_id=42,
        page_texts=[
            (1, "Pedido 2026/154 con referencia ABC123 " * 90),
            (2, ""),
        ],
    )

    assert chunks
    assert all(chunk.document_id == 42 for chunk in chunks)
    assert {chunk.page_number for chunk in chunks} == {1}
    assert calls and "ABC123" in calls[0][0]


def test_worker_notifies_only_when_retries_are_exhausted(monkeypatch):
    from app.workers import tasks as worker_tasks

    notifications: list[tuple[int, int, str]] = []
    calls: list[bool] = []

    class FakeDb:
        def get(self, model, item_id):
            return type("Row", (), {"status": "processing"})()

        def expire_all(self):
            pass

        def commit(self):
            pass

        def close(self):
            pass

    def fail_processing(db, *, document_id, job_id, final_failure=True):
        calls.append(final_failure)
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_tasks, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(worker_tasks, "process_document", fail_processing)
    monkeypatch.setattr(
        worker_tasks,
        "notify_failed",
        lambda *, job_id, document_id, exc: notifications.append((job_id, document_id, str(exc))),
    )

    worker_tasks.process_document_task.request.retries = 1
    try:
        worker_tasks.process_document_task.run(12, 34)
    except RuntimeError:
        pass
    else:
        raise AssertionError("task should re-raise processing failures")

    worker_tasks.process_document_task.request.retries = worker_tasks.process_document_task.max_retries
    try:
        worker_tasks.process_document_task.run(12, 34)
    except RuntimeError:
        pass
    else:
        raise AssertionError("task should re-raise processing failures")

    assert calls == [False, True]
    assert notifications == [(34, 12, "boom")]


def test_process_document_intermediate_retry_does_not_mark_final_failure_or_emit_webhook(monkeypatch):
    sessions = _session_factory()
    webhooks: list[str] = []

    monkeypatch.setattr(document_service, "_process_full_parse", lambda db, document: (_ for _ in ()).throw(RuntimeError("ocr down")))
    monkeypatch.setattr(document_service, "emit_integration_webhook", lambda event, payload: webhooks.append(event))

    with sessions() as db:
        document = _document(db, "scan.pdf", status="pending", quality_status="pending")
        job = ExtractionJob(document_id=document.id, job_type="extract", status="pending")
        db.add(job)
        db.commit()

        try:
            document_service.process_document(db, document_id=document.id, job_id=job.id, final_failure=False)
        except RuntimeError:
            pass
        else:
            raise AssertionError("processing failure should be re-raised for Celery autoretry")

        db.refresh(document)
        db.refresh(job)
        assert document.status == "processing"
        assert job.status == "retrying"
        assert webhooks == []


def test_process_document_final_retry_marks_failed_and_emits_one_webhook(monkeypatch):
    sessions = _session_factory()
    webhooks: list[str] = []

    monkeypatch.setattr(document_service, "_process_full_parse", lambda db, document: (_ for _ in ()).throw(RuntimeError("ocr down")))
    monkeypatch.setattr(document_service, "emit_integration_webhook", lambda event, payload: webhooks.append(event))

    with sessions() as db:
        document = _document(db, "scan.pdf", status="pending", quality_status="pending")
        job = ExtractionJob(document_id=document.id, job_type="extract", status="pending")
        db.add(job)
        db.commit()

        try:
            document_service.process_document(db, document_id=document.id, job_id=job.id, final_failure=True)
        except RuntimeError:
            pass
        else:
            raise AssertionError("processing failure should be re-raised for Celery failure handling")

        db.refresh(document)
        db.refresh(job)
        assert document.status == "failed"
        assert job.status == "failed"
        assert webhooks == ["document.failed"]


def test_actual_enqueue_calls_route_by_document_and_job_type(monkeypatch, tmp_path: Path):
    calls: list[dict] = []
    sessions = _session_factory()
    monkeypatch.setattr(settings, "files_dir", tmp_path / "files")
    monkeypatch.setattr("app.services.document_registration_service.inspect_file_for_ingestion", lambda source: type("Result", (), {"allowed": True, "reason": "ok"})())
    monkeypatch.setattr("app.workers.tasks.process_document_task.apply_async", lambda *args, **kwargs: calls.append({"args": args, "kwargs": kwargs}))

    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    xlsx = tmp_path / "sheet.xlsx"
    xlsx.write_bytes(b"xlsx")

    with sessions() as db:
        pdf_doc, _ = document_service.register_existing_file(db, source=pdf, enqueue=True)
        xlsx_doc, _ = document_service.register_existing_file(db, source=xlsx, enqueue=True)
        embeddings_job = document_service.reprocess_document(db, document=xlsx_doc, user=None, enqueue=True, job_type="reprocess:embeddings")
        assert embeddings_job.job_type == "reprocess:embeddings"

    assert calls[0]["kwargs"]["queue"] == "ocr_heavy"
    assert calls[0]["kwargs"]["args"][0] == pdf_doc.id
    assert calls[1]["kwargs"]["queue"] == "text_fast"
    assert calls[1]["kwargs"]["args"][0] == xlsx_doc.id
    assert calls[2]["kwargs"]["queue"] == "embeddings"


def test_celery_app_does_not_pin_process_document_task_to_text_fast():
    from app.workers.celery_app import celery_app

    assert "app.workers.tasks.process_document_task" not in celery_app.conf.task_routes


def test_cancel_pending_reprocess_preserves_processed_document_status():
    sessions = _session_factory()
    with sessions() as db:
        document = _document(db, "scan.pdf", status="processed", quality_status="processed_ok")
        job = document_service.reprocess_document(db, document=document, user=None, enqueue=False)
        assert document.status == "pending"

        cancel_pending_job(db, job)
        db.commit()
        db.refresh(document)

    assert document.status == "processed"


def test_bulk_reprocess_skips_active_jobs_and_respects_capacity(monkeypatch):
    sessions = _session_factory()
    monkeypatch.setattr(settings, "ingestion_max_pending_jobs", 2)
    monkeypatch.setattr("app.workers.tasks.process_document_task.apply_async", lambda *args, **kwargs: None)

    with sessions() as db:
        user = _user(db)
        first = _document(db, "one.pdf")
        second = _document(db, "two.pdf")
        third = _document(db, "three.pdf")
        db.add(ExtractionJob(document_id=first.id, job_type="reprocess:full", status="pending"))
        db.commit()

        result = bulk_reprocess_documents(db, filters=BulkReprocessFilters(ids=[first.id, second.id, third.id], limit=10), user=user)
        repeated = bulk_reprocess_documents(db, filters=BulkReprocessFilters(ids=[first.id, second.id, third.id], limit=10), user=user)

    assert result.matched == 3
    assert result.enqueued == 1
    assert result.skipped == 2
    assert repeated.enqueued == 0
    assert repeated.skipped == 3


def test_queue_status_counts_use_routed_queue_for_document_type():
    sessions = _session_factory()
    with sessions() as db:
        pdf = _document(db, "scan.pdf", status="pending")
        xlsx = _document(db, "sheet.xlsx", status="pending")
        db.add_all(
            [
                ExtractionJob(document_id=pdf.id, job_type="extract", status="pending"),
                ExtractionJob(document_id=xlsx.id, job_type="extract", status="pending"),
                ExtractionJob(document_id=xlsx.id, job_type="reprocess:embeddings", status="pending"),
            ]
        )
        db.commit()

        status = build_queue_control_status(db)

    assert status.queues["ocr_heavy"]["pending"] == 1
    assert status.queues["text_fast"]["pending"] == 1
    assert status.queues["embeddings"]["pending"] == 1


def test_webhook_timeout_failure_is_bounded_and_non_fatal(monkeypatch):
    """A slow webhook (httpx timeout) must be caught by the delivery worker,
    retried, and never crash the sweep — bounded and non-fatal.

    ``emit_integration_webhook`` only *enqueues* the row (it never calls httpx
    synchronously); the actual send with the timeout lives in the delivery
    worker (``deliver_pending_webhooks_task``), which is what this test drives.
    """
    import httpx
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database.base import Base
    from app.models import WebhookOutbox
    from app.services import webhooks as webhooks_service
    from app.workers import webhooks_tasks

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(webhooks_service.settings, "integration_webhook_url", "https://example.test/webhook")
    monkeypatch.setattr(webhooks_service.settings, "integration_webhook_events", ["document.processed"])
    monkeypatch.setattr(webhooks_service.settings, "integration_webhook_timeout_seconds", 1.25)
    monkeypatch.setattr(webhooks_service.settings, "integration_webhook_secret", "")

    calls: list[float] = []

    def fail_post(*args, **kwargs):
        calls.append(kwargs["timeout"])
        raise httpx.TimeoutException("slow webhook")

    monkeypatch.setattr(webhooks_tasks.httpx, "post", fail_post)
    monkeypatch.setattr(webhooks_tasks, "_get_session", lambda: Session())

    db = Session()
    try:
        webhooks_service.enqueue_webhook(db, event="document.processed", payload={"document_id": 1})
        db.commit()

        result = webhooks_tasks.deliver_pending_webhooks_task()
    finally:
        db.close()

    assert result["attempted"] == 1
    assert result["failed"] == 1
    assert result["delivered"] == 0
    assert calls == [1.25]

    # Non-fatal: the row is rescheduled (back to ``pending``), not lost or
    # dead-lettered on the first failure.
    session = Session()
    try:
        row = session.get(WebhookOutbox, 1)
        assert row is not None
        assert row.status == "pending"
        assert row.attempts == 1
    finally:
        session.close()


def test_webhook_disabled_event_does_not_call_http(monkeypatch):
    from app.services import webhooks

    monkeypatch.setattr(webhooks.settings, "integration_webhook_url", "https://example.test/webhook")
    monkeypatch.setattr(webhooks.settings, "integration_webhook_events", ["document.processed"])

    # A disabled event short-circuits before any DB session is opened and
    # before any HTTP call is made, so emit_integration_webhook must never
    # reach httpx.
    result = webhooks.emit_integration_webhook("document.failed", {"document_id": 1})

    assert result == {"sent": False, "reason": "event_disabled"}


def test_production_compose_splits_workers_and_healthchecks():
    compose = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"
    content = compose.read_text(encoding="utf-8")

    # Four dedicated workers, each pinned to its own queue.
    assert "worker-ocr-gpu:" in content
    assert "worker-embeddings-gpu:" in content
    assert "worker-text-cpu:" in content
    assert "worker-maintenance:" in content

    # Queue routing: heavy OCR + embeddings on GPU workers, text/classification
    # + celery default on the CPU worker, maintenance on its own worker.
    assert "-Q ocr_heavy" in content
    assert "-Q embeddings" in content
    assert "-Q text_fast,celery" in content
    assert "-Q maintenance" in content

    # Every worker exposes a healthcheck so the orchestrator can detect hangs.
    assert content.count("healthcheck:") >= 6
