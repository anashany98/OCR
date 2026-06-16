from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.database.base import Base
from app.models import Document, ExtractionJob, User
from app.services import document_service
from app.services.queue_control import build_queue_control_status, cancel_pending_job
from app.services.document_service import (
    mode_requires_file_parse,
    prepare_document_chunks,
    processing_mode_from_job_type,
)
from app.services.operations import (
    ALERT_DEFINITIONS,
    BulkReprocessFilters,
    bulk_reprocess_documents,
    normalize_bulk_reprocess_filters,
)


def _session_factory() -> sessionmaker[Session]:
    """Return a sqlite in-memory session factory.

    The autouse ``_sqlite_safe_metadata`` fixture in
    ``tests/conftest.py`` strips the Postgres-only
    ``Computed("to_tsvector('simple', ...)")`` column from
    ``DocumentChunk`` for the duration of every test, so the
    DDL emitted by ``Base.metadata.create_all`` is plain SQLite
    SQL. The tests only use the sqlite session to exercise the
    Python control flow (status transitions, retry semantics,
    queue routing); they never query ``tsv``.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _document(
    db: Session, filename: str, *, status: str = "processed", quality_status: str = "processed_ok"
) -> Document:
    document = Document(
        original_filename=filename,
        stored_filename=f"aa/{filename}",
        source_path=f"/data/input/{filename}",
        file_hash=(filename.replace(".", "")[:1] or "a") * 64,
        mime_type="application/octet-stream",
        extension=Path(filename).suffix.lower(),
        file_size=10,
        document_type="plano"
        if Path(filename).suffix.lower() in {".pdf", ".png", ".jpg"}
        else "excel",
        status=status,
        quality_status=quality_status,
        processed_at=datetime.utcnow() if status in {"processed", "needs_review"} else None,
    )
    db.add(document)
    db.flush()
    return document


def _user(db: Session) -> User:
    user = User(
        email="admin@local", name="Admin", password_hash="hash", role="admin", is_active=True
    )
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
    """``prepare_document_chunks`` lives in
    ``app.services.document_embedding_pipeline`` (re-exported by
    ``document_service`` for backward compatibility). The function
    imports ``embed_many`` and ``should_create_embeddings`` at
    module top, so the test must patch those names where the
    implementation looks them up — i.e. on the
    ``document_embedding_pipeline`` module — not on
    ``document_service``.
    """
    from app.services import document_embedding_pipeline

    calls: list[list[str]] = []

    def fake_embed_many(texts):
        calls.append(list(texts))
        return [[0.1] * 1024 for _ in texts]

    monkeypatch.setattr(document_embedding_pipeline, "should_create_embeddings", lambda: True)
    monkeypatch.setattr(document_embedding_pipeline, "embed_many", fake_embed_many)

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
    """The Celery task wrapper must only fire
    :func:`notify_failed` on the **final** attempt of a
    non-retryable error. An intermediate retry (Celery still has
    attempts left) should mark the job as failed and Reject the
    message, but must NOT publish a notification — otherwise the
    admin UI / on-call gets spammed when a single poison message
    gets re-routed.
    """
    from app.workers import tasks as worker_tasks
    from app.services import notification as notification_module

    notifications: list[tuple[int, int, str]] = []
    calls: list[bool] = []

    class FakeJob:
        status: str = "pending"
        error_message: str | None = None
        finished_at = None
        retries: int = 0

    class FakeDb:
        def get(self, model, item_id):
            return FakeJob()

        def close(self):
            pass

        def expire_all(self):
            pass

        def commit(self):
            pass

        def add(self, obj):
            pass

        def refresh(self, obj):
            pass

    def fail_processing(db, *, document_id, job_id, final_failure=True):
        calls.append(final_failure)
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_tasks, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(worker_tasks, "process_document", fail_processing)
    monkeypatch.setattr(
        notification_module.notification_service,
        "notify_job_failed",
        lambda job_id, document_id, error: notifications.append((job_id, document_id, error)),
    )

    def _unwrap_reject(exc: BaseException) -> BaseException:
        """Unwrap a Celery ``Reject`` to its original cause.

        ``process_document_task`` raises
        :class:`celery.exceptions.Reject` (with ``requeue=False``)
        when a permanent error happens, to stop Celery from
        retrying the message. ``Reject.args[0]`` is the original
        exception; we unwrap so the test can check that the
        underlying failure is a ``RuntimeError``.
        """
        from celery.exceptions import Reject as CeleryReject

        if isinstance(exc, CeleryReject) and exc.args:
            return exc.args[0]
        return exc

    # Simulate the intermediate retry: Celery has used 1 of 3
    # retries, so ``final_failure`` is False inside the task.
    worker_tasks.process_document_task.request.retries = 1
    try:
        worker_tasks.process_document_task.run(12, 34)
    except Exception as exc:
        if not isinstance(_unwrap_reject(exc), RuntimeError):
            raise
    else:
        raise AssertionError("task should re-raise processing failures")

    # Simulate the final attempt: retries == max_retries, so
    # ``final_failure`` is True and the notification fires.
    worker_tasks.process_document_task.request.retries = (
        worker_tasks.process_document_task.max_retries
    )
    try:
        worker_tasks.process_document_task.run(12, 34)
    except Exception as exc:
        if not isinstance(_unwrap_reject(exc), RuntimeError):
            raise
    else:
        raise AssertionError("task should re-raise processing failures")

    assert calls == [False, True], (
        f"expected final_failure=[False, True] (intermediate, final), got {calls!r}"
    )
    assert len(notifications) == 1, (
        f"expected exactly one notification (final attempt only), got {notifications!r}"
    )
    assert notifications[0][0] == 34  # job_id
    assert notifications[0][1] == 12  # document_id
    assert "boom" in notifications[0][2]


def test_process_document_intermediate_retry_does_not_mark_final_failure_or_emit_webhook(
    monkeypatch,
):
    """An intermediate retry (``final_failure=False``) must set
    the job to ``retrying`` and the document back to
    ``processing``, but must NOT emit the ``document.failed``
    webhook. The webhook is the operator-facing signal that the
    document is permanently dead; an intermediate retry is a
    transient, internal state.
    """
    from app.services import document_processing_core

    sessions = _session_factory()
    webhooks: list[str] = []

    monkeypatch.setattr(
        document_processing_core,
        "_process_full_parse",
        lambda db, document: (_ for _ in ()).throw(RuntimeError("ocr down")),
    )
    monkeypatch.setattr(
        document_processing_core,
        "emit_integration_webhook",
        lambda event, payload: webhooks.append(event),
    )

    with sessions() as db:
        document = _document(db, "scan.pdf", status="pending", quality_status="pending")
        job = ExtractionJob(document_id=document.id, job_type="extract", status="pending")
        db.add(job)
        db.commit()

        try:
            document_service.process_document(
                db, document_id=document.id, job_id=job.id, final_failure=False
            )
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
    """The final attempt (``final_failure=True``) must mark the
    document and the job as ``failed`` and emit exactly one
    ``document.failed`` webhook so the operator can see the
    permanent failure in the admin UI.
    """
    from app.services import document_processing_core

    sessions = _session_factory()
    webhooks: list[str] = []

    monkeypatch.setattr(
        document_processing_core,
        "_process_full_parse",
        lambda db, document: (_ for _ in ()).throw(RuntimeError("ocr down")),
    )
    monkeypatch.setattr(
        document_processing_core,
        "emit_integration_webhook",
        lambda event, payload: webhooks.append(event),
    )

    with sessions() as db:
        document = _document(db, "scan.pdf", status="pending", quality_status="pending")
        job = ExtractionJob(document_id=document.id, job_type="extract", status="pending")
        db.add(job)
        db.commit()

        try:
            document_service.process_document(
                db, document_id=document.id, job_id=job.id, final_failure=True
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError(
                "processing failure should be re-raised for Celery failure handling"
            )

        db.refresh(document)
        db.refresh(job)
        assert document.status == "failed"
        assert job.status == "failed"
        assert webhooks == ["document.failed"]


def test_actual_enqueue_calls_route_by_document_and_job_type(monkeypatch, tmp_path: Path):
    calls: list[dict] = []
    sessions = _session_factory()
    monkeypatch.setattr(settings, "files_dir", tmp_path / "files")
    monkeypatch.setattr(
        document_service,
        "inspect_file_for_ingestion",
        lambda source: type("Result", (), {"allowed": True, "reason": "ok"})(),
    )
    monkeypatch.setattr(
        "app.workers.tasks.process_document_task.apply_async",
        lambda *args, **kwargs: calls.append({"args": args, "kwargs": kwargs}),
    )

    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    xlsx = tmp_path / "sheet.xlsx"
    # A real .xlsx is a zip with a PK\x03\x04 header. The earlier
    # test wrote b"xlsx" which the file-security inspector
    # rejected (``invalid_xlsx_signature``), so the register path
    # set the document to ``needs_review`` and never enqueued an
    # ``extract`` job — the test then only saw 2 calls instead
    # of 3 and ``calls[1]`` was the embeddings reprocess.
    xlsx.write_bytes(b"PK\x03\x04" + b"\x00" * 26)

    with sessions() as db:
        pdf_doc, _ = document_service.register_existing_file(db, source=pdf, enqueue=True)
        xlsx_doc, _ = document_service.register_existing_file(db, source=xlsx, enqueue=True)
        embeddings_job = document_service.reprocess_document(
            db, document=xlsx_doc, user=None, enqueue=True, job_type="reprocess:embeddings"
        )
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
    monkeypatch.setattr(
        "app.workers.tasks.process_document_task.apply_async", lambda *args, **kwargs: None
    )

    with sessions() as db:
        user = _user(db)
        first = _document(db, "one.pdf")
        second = _document(db, "two.pdf")
        third = _document(db, "three.pdf")
        db.add(ExtractionJob(document_id=first.id, job_type="reprocess:full", status="pending"))
        db.commit()

        result = bulk_reprocess_documents(
            db,
            filters=BulkReprocessFilters(ids=[first.id, second.id, third.id], limit=10),
            user=user,
        )
        repeated = bulk_reprocess_documents(
            db,
            filters=BulkReprocessFilters(ids=[first.id, second.id, third.id], limit=10),
            user=user,
        )

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
                ExtractionJob(
                    document_id=xlsx.id, job_type="reprocess:embeddings", status="pending"
                ),
            ]
        )
        db.commit()

        status = build_queue_control_status(db)

    assert status.queues["ocr_heavy"]["pending"] == 1
    assert status.queues["text_fast"]["pending"] == 1
    assert status.queues["embeddings"]["pending"] == 1


def test_webhook_timeout_failure_is_bounded_and_non_fatal(monkeypatch):
    """The delivery worker (``app.workers.webhooks_tasks``) must
    pass ``settings.integration_webhook_timeout_seconds`` as the
    ``httpx.post`` timeout and must not let a slow receiver
    propagate the exception to the rest of the system. A failure
    keeps the row in the outbox with ``attempts`` incremented and
    the next Beat tick retries it.
    """
    from app.services import webhooks
    from app.workers import webhooks_tasks

    calls: list[dict] = []

    def slow_post(url, **kwargs):
        calls.append({"url": url, "timeout": kwargs.get("timeout")})
        raise httpx.TimeoutException("slow webhook")

    monkeypatch.setattr(
        webhooks.settings, "integration_webhook_url", "https://example.test/webhook"
    )
    monkeypatch.setattr(webhooks.settings, "integration_webhook_events", ["document.processed"])
    monkeypatch.setattr(webhooks.settings, "integration_webhook_timeout_seconds", 1.25)
    monkeypatch.setattr(webhooks_tasks.httpx, "post", slow_post)

    sessions = _session_factory()
    with sessions() as db:
        # Enqueue the row directly so we exercise the same code
        # path that ``emit_integration_webhook`` would, but
        # without depending on the SessionLocal wiring.
        from app.services.webhooks import enqueue_webhook

        row = enqueue_webhook(db, event="document.processed", payload={"document_id": 1})
        assert row is not None
        db.commit()
        row_id = row.id

    # Now run the delivery task against the same in-memory DB. It
    # must mark the row as pending (not raise) and respect the
    # configured timeout.
    with sessions() as db:
        monkeypatch.setattr(webhooks_tasks, "SessionLocal", sessions)
        # Should not raise even though httpx.post raises TimeoutException.
        webhooks_tasks.deliver_pending_webhooks_task.run()
        # The row stays in the outbox; attempts is incremented.
        from app.models import WebhookOutbox

        refreshed = db.get(WebhookOutbox, row_id)
        assert refreshed is not None
        # attempts=1 because one delivery attempt happened and failed.
        assert refreshed.attempts >= 1

    assert calls, "httpx.post was never called by the delivery worker"
    assert calls[0]["timeout"] == 1.25


def test_webhook_disabled_event_does_not_call_http(monkeypatch):
    """When the configured ``integration_webhook_events`` does
    not include the event being emitted, ``emit_integration_webhook``
    must short-circuit and return ``{sent: False, reason: 'event_disabled'}``
    without touching the outbox or scheduling any HTTP work.
    """
    from app.services import webhooks

    monkeypatch.setattr(
        webhooks.settings, "integration_webhook_url", "https://example.test/webhook"
    )
    monkeypatch.setattr(webhooks.settings, "integration_webhook_events", ["document.processed"])

    # Sentinel: any enqueue attempt would fail the test.
    monkeypatch.setattr(
        webhooks,
        "enqueue_webhook",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("enqueue_webhook should not be called for disabled events")
        ),
    )

    result = webhooks.emit_integration_webhook("document.failed", {"document_id": 1})

    assert result == {"sent": False, "reason": "event_disabled"}


def test_production_compose_splits_workers_and_healthchecks():
    """The production compose must run a separate worker for
    OCR-heavy traffic (high memory budget, low concurrency) so a
    stuck Paddle job cannot starve text ingestion. The test
    accepts both the current 3-worker split (``worker-fast`` /
    ``worker-maintenance`` / ``ocr-worker``) and the older
    consolidated layout (``worker`` + ``ocr-worker``); the
    invariant is that the queues ``text_fast``, ``embeddings``,
    ``maintenance`` and ``ocr_heavy`` are all drained by some
    worker.
    """
    compose = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"
    content = compose.read_text(encoding="utf-8")

    # An OCR-heavy worker must exist (high mem, low concurrency).
    assert "ocr-worker:" in content
    assert "-Q ocr_heavy" in content

    # The fast / maintenance / embeddings queues must each be
    # drained by some worker — the test does not care whether they
    # are consolidated into one ``worker`` service or split into
    # ``worker-fast`` + ``worker-maintenance``.
    fast_queues = {"text_fast", "embeddings", "maintenance"}
    queue_pattern = re.compile(r"-Q\s+([A-Za-z0-9_,\s]+?)(?=\s+--|\s*$)")
    covered_queues: set[str] = set()
    for match in queue_pattern.finditer(content):
        covered_queues.update(queue.strip() for queue in match.group(1).split(",") if queue.strip())
    missing = fast_queues - covered_queues
    assert not missing, (
        f"Queues {sorted(missing)} are not drained by any worker "
        f"in docker-compose.prod.yml. Found: {sorted(covered_queues)}"
    )

    # A backend service plus at least one worker service must be
    # declared (consolidated ``worker`` OR split ``worker-fast``).
    assert "backend:" in content
    assert ("worker:" in content) or ("worker-fast:" in content)

    # Every long-running service must have a healthcheck so the
    # orchestrator can detect a dead worker.
    assert content.count("healthcheck:") >= 4
