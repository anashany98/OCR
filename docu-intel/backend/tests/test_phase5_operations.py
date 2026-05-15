from app.services import document_service
from app.services.document_service import mode_requires_file_parse, prepare_document_chunks, processing_mode_from_job_type
from app.services.operations import ALERT_DEFINITIONS, BulkReprocessFilters, normalize_bulk_reprocess_filters


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
    monkeypatch.setattr(document_service, "embed_many", fake_embed_many)

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


def test_worker_notifies_when_processing_job_fails(monkeypatch):
    from app.workers import tasks as worker_tasks

    notifications: list[tuple[int, int, str]] = []

    class FakeDb:
        def get(self, model, item_id):
            return object()

        def close(self):
            pass

    def fail_processing(db, *, document_id, job_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_tasks, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(worker_tasks, "process_document", fail_processing)
    monkeypatch.setattr(
        worker_tasks.notification_service,
        "notify_job_failed",
        lambda job_id, document_id, message: notifications.append((job_id, document_id, message)),
    )

    try:
        worker_tasks.process_document_task.run(12, 34)
    except RuntimeError:
        pass
    else:
        raise AssertionError("task should re-raise processing failures")

    assert notifications == [(34, 12, "boom")]
