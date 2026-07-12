"""Verification tests for the review-driven PR.

Each function maps to one of the 11 items in the review brief
(``O1``-``O11``). The tests focus on the *behavioural change* of
the fix, not on internal helpers, so they stay robust to future
refactors.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date
from pathlib import Path

import pytest

from app.ai.context import ContextItem
from app.ai.validation import response_fabricates_documents
from app.parsers.types import ExtractedBlock, ExtractedPage
from app.services.business_extraction import (
    _extract_lines_for_document,
    _has_table_blocks,
    _parse_date,
    _parse_markdown_table,
    extract_budget,
)
from app.services.dates import (
    DATE_PATTERN,
    first_date_in_text,
    find_dates_in_text,
    parse_spanish_date,
)
from app.services.file_security import (
    BLOCKED_OFFICE_EXTENSIONS,
    inspect_file_for_ingestion,
)
from app.services.tenant_access import (
    AccessScope,
    DocumentAccessMetadata,
    metadata_allows_scope,
)


# ---------------------------------------------------------------------------
# Item 1 - HyDE typo (verified in unit form, not via full search pipeline)
# ---------------------------------------------------------------------------


def test_hyde_variable_name_is_consistent():
    """The hypothetical-answer variable inside ``_hyde_embed`` must be
    spelled ``hypothetical`` (not ``hypetical``) so the embed call
    does not raise NameError. We assert it indirectly by importing
    the function and inspecting its source for the typo."""
    from app.services import search_service

    source = Path(search_service.__file__).read_text(encoding="utf-8")
    # The misspelling must be gone.
    assert "hypetical" not in source
    # The well-spelled form is used in the embed call.
    assert "embed_query_text(hypothetical)" in source


# ---------------------------------------------------------------------------
# Item 2 - multi-query reformulation is wired into search_semantic
# ---------------------------------------------------------------------------


def test_multi_query_reformulations_helper_in_source():
    """``_multi_query_reformulations`` must be called from
    ``search_semantic`` so the helper stops being dead code."""
    from app.services import search_service

    source = Path(search_service.__file__).read_text(encoding="utf-8")
    # The helper definition is still present.
    assert "def _multi_query_reformulations" in source
    # And the caller uses it.
    assert "_multi_query_reformulations(normalized)" in source
    # The RRF merger must be present too.
    assert "_merge_reformulation_results" in source


def test_merge_reformulation_results_rrf_boosts_overlap():
    """A chunk that appears in *two* reformulations must outrank a
    chunk that appears in *one* even when its single-pass rank is
    worse."""
    from app.services.search_service import (
        SearchResult,
        _merge_reformulation_results,
    )

    a = SearchResult(
        document_id=1, original_filename="a.pdf", document_type="presupuesto",
        status="processed_ok", page_number=1, block_id=None, score=0.9,
        excerpt="x", ocr_confidence=None, source_type="semantic_chunk", source_path=None,
    )
    b = SearchResult(
        document_id=2, original_filename="b.pdf", document_type="pedido",
        status="processed_ok", page_number=1, block_id=None, score=0.95,
        excerpt="y", ocr_confidence=None, source_type="semantic_chunk", source_path=None,
    )
    # List 1: a first, b second. List 2: a absent, b first.
    merged = _merge_reformulation_results(
        [[a, b], [b]],
        limit=5,
    )
    # b appears twice (ranks 1, 0) and a appears once (rank 0).
    # b's RRF score: 1/(60+1+1) + 1/(60+0+1) ~ 0.0328
    # a's RRF score: 1/(60+0+1) ~ 0.0164
    assert merged[0].document_id == 2
    assert merged[1].document_id == 1
    assert merged[0].source_type == "semantic_multi_query"


# ---------------------------------------------------------------------------
# Item 3 - VAT regex (NOT CONFIRMED, just sanity check)
# ---------------------------------------------------------------------------


def test_amount_from_label_vat_pattern_matches_21_percent():
    """The ``_amount_from_label`` regex must accept ``IVA 21%: 21,00 EUR``."""
    from app.services.business_extraction import _amount_from_label

    amount, currency = _amount_from_label(
        "IVA 21%: 21,00 EUR",
        ["iva", "importe iva"],
    )
    assert amount == 21.0
    assert currency == "EUR"


# ---------------------------------------------------------------------------
# Item 4 - learned rules are wired in
# ---------------------------------------------------------------------------


def test_apply_classification_and_extraction_passes_learned_rules(monkeypatch):
    """``_apply_classification_and_extraction`` must pass the
    loaded learned rules to ``classify_document`` so operator
    approvals actually affect production classification.

    We patch the heavy DB-backed helpers so the test stays pure.
    """
    from app.services import document_processing_core
    from app.services.classification import ClassificationResult

    captured: dict = {}

    def fake_get_rules(db):
        return ["RULE_A", "RULE_B"]

    def fake_classify(*args, learned_rules=None, **kwargs):
        captured["learned_rules"] = learned_rules
        return ClassificationResult("presupuesto", 0.9, ["learned:RULE_A"])

    monkeypatch.setattr(
        document_processing_core, "_get_cached_learned_rules", fake_get_rules
    )
    monkeypatch.setattr(
        document_processing_core, "classify_document", fake_classify
    )
    # Stub the rest of the pipeline so the function returns early
    # without hitting the DB.
    monkeypatch.setattr(
        document_processing_core, "persist_business_extraction",
        lambda *a, **kw: type("R", (), {"needs_review": False})(),
    )
    monkeypatch.setattr(
        document_processing_core, "_get_effective_persist_business_extraction",
        lambda: document_processing_core.persist_business_extraction,
    )
    monkeypatch.setattr(
        document_processing_core, "persist_plan_extraction",
        lambda *a, **kw: type("R", (), {"needs_review": False})(),
    )
    monkeypatch.setattr(
        document_processing_core, "_get_effective_persist_plan_extraction",
        lambda: document_processing_core.persist_plan_extraction,
    )
    monkeypatch.setattr(
        document_processing_core, "evaluate_document_quality",
        lambda *a, **kw: type("Q", (), {"needs_review": False})(),
    )
    monkeypatch.setattr(
        document_processing_core, "_get_effective_evaluate_document_quality",
        lambda: document_processing_core.evaluate_document_quality,
    )
    monkeypatch.setattr(
        document_processing_core, "update_document_quality",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        document_processing_core, "_get_effective_update_document_quality",
        lambda: document_processing_core.update_document_quality,
    )

    fake_db = type("DB", (), {"execute": lambda self, *a, **kw: None, "flush": lambda self, *a, **kw: None})()

    fake_doc = type("D", (), {})()
    fake_doc.original_filename = "demo.pdf"
    fake_doc.source_path = "/x"
    fake_doc.id = 1

    document_processing_core._apply_classification_and_extraction(
        fake_db,  # type: ignore[arg-type]
        fake_doc,
        text="hola",
        page_count=1,
        low_ocr_confidences=[],
    )
    assert captured["learned_rules"] == ["RULE_A", "RULE_B"]


def test_get_cached_learned_rules_uses_ttl(monkeypatch):
    """The 60 s TTL means a second call inside the window does not
    re-hit the DB."""
    from app.services import document_processing_core

    call_count = {"n": 0}

    def fake_load(db):
        call_count["n"] += 1
        return []

    monkeypatch.setattr(
        document_processing_core, "_load_active_learned_rules", fake_load
    )
    document_processing_core.reset_learned_rules_cache()
    document_processing_core._get_cached_learned_rules(None)  # type: ignore[arg-type]
    document_processing_core._get_cached_learned_rules(None)  # type: ignore[arg-type]
    document_processing_core._get_cached_learned_rules(None)  # type: ignore[arg-type]
    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# Item 5 - event loop misuse
# ---------------------------------------------------------------------------


def test_run_coro_sync_works_without_existing_loop():
    from app.parsers.pdf import _run_coro_sync

    async def coro() -> str:
        await asyncio.sleep(0)
        return "ok"

    assert _run_coro_sync(coro()) == "ok"


def test_run_coro_sync_works_inside_running_loop():
    """The previous code crashed when the sync wrapper was called
    from inside a running event loop (FastAPI request handler).
    The fix must transparently off-load to a worker thread."""
    from app.parsers.pdf import _run_coro_sync

    async def coro() -> int:
        await asyncio.sleep(0)
        return 42

    async def main() -> int:
        return _run_coro_sync(coro())

    # If the bug regressed, ``_run_coro_sync`` would raise
    # ``RuntimeError: asyncio.run() cannot be called from a running
    # event loop`` and this test would fail.
    assert asyncio.run(main()) == 42


# ---------------------------------------------------------------------------
# Item 6 - duplicate denied_tags check
# ---------------------------------------------------------------------------


def test_metadata_allows_scope_denied_tags_still_block_when_assigned():
    """Even after removing the second duplicate check, denied tags
    must still block an *assigned* document (the very first check
    covers both branches now)."""
    scope = AccessScope(
        principal_type="user",
        principal_id="1",
        denied_tags={"precios"},
    )
    metadata = DocumentAccessMetadata(
        document_id=1,
        tags_json=["precios"],
        assignment_status="assigned",
        assignment_source="folder_rule",
        hotel_id=None,
        chain_id=None,
    )
    assert metadata_allows_scope(metadata, scope) is False


def test_metadata_allows_scope_denied_tags_still_block_when_unassigned():
    scope = AccessScope(
        principal_type="user", principal_id="1",
        denied_tags={"contabilidad"}, allow_unassigned_documents=True,
    )
    metadata = DocumentAccessMetadata(
        document_id=1, tags_json=["contabilidad"],
        assignment_status="quarantine", assignment_source="none",
        hotel_id=None, chain_id=None,
    )
    assert metadata_allows_scope(metadata, scope) is False


def test_metadata_allows_scope_source_contains_only_one_denied_check():
    """Belt-and-braces: the source must contain a single
    ``denied_tags & tags`` intersection in ``metadata_allows_scope``."""
    from app.services import tenant_access

    source = Path(tenant_access.__file__).read_text(encoding="utf-8")
    # Find the function body and count intersections.
    body = re.search(
        r"def metadata_allows_scope.*?(?=\ndef |\Z)", source, flags=re.DOTALL
    )
    assert body is not None
    intersection_count = body.group(0).count("scope.denied_tags & tags")
    assert intersection_count == 1, (
        f"expected exactly 1 denied_tags intersection, got {intersection_count}"
    )


# ---------------------------------------------------------------------------
# Item 7 - fabrication check
# ---------------------------------------------------------------------------


def _item(filename: str, summary: str, excerpt: str | None = None) -> ContextItem:
    return ContextItem(
        title=filename,
        summary=summary,
        document_filename=filename,
        excerpt=excerpt or summary,
    )


def test_fabrication_accepts_filename_in_context():
    items = [_item("F-2026-044.pdf", "Factura F-2026-044 por 121,00 EUR")]
    assert response_fabricates_documents(
        "Segun F-2026-044.pdf el total es 121,00 EUR.", items
    ) is False


def test_fabrication_rejects_unknown_filename():
    items = [_item("F-2026-044.pdf", "Factura F-2026-044 por 121,00 EUR")]
    assert response_fabricates_documents(
        "Segun F-2026-999.pdf el total es 121,00 EUR.", items
    ) is True


def test_fabrication_rejects_hallucinated_invoice_number():
    items = [_item("F-2026-044.pdf", "Factura F-2026-044 por 121,00 EUR")]
    assert response_fabricates_documents(
        "Existe la factura F-2026-999 por 50,00 EUR.", items
    ) is True


def test_fabrication_rejects_hallucinated_amount():
    items = [_item("F-2026-044.pdf", "Factura F-2026-044 por 121,00 EUR")]
    # The number is real, but the amount is invented.
    assert response_fabricates_documents(
        "Segun F-2026-044.pdf el total es 999,00 EUR.", items
    ) is True


def test_fabrication_accepts_amount_present_in_context():
    items = [_item("F-2026-044.pdf", "Factura F-2026-044 por 121,00 EUR")]
    assert response_fabricates_documents(
        "La factura F-2026-044.pdf asciende a 121,00 EUR.", items
    ) is False


def test_fabrication_tolerates_year_only():
    items = [_item("F-2026-044.pdf", "Factura del ejercicio 2026 por 121,00 EUR")]
    # Year-only "2026" must not be flagged as a fabricated document
    # number. The normaliser requires >= 4 alphanumeric chars and a
    # numeric-only 4-digit year is excluded by the regex itself.
    assert response_fabricates_documents(
        "Documento del ano 2026, factura F-2026-044.pdf, 121,00 EUR.", items
    ) is False


def test_fabrication_accepts_document_number_from_source_path():
    items = [
        ContextItem(
            title="APROBADO.pdf",
            summary="Presupuesto aprobado por 121,00 EUR",
            document_filename="APROBADO.pdf",
            source_path="clientes/CEO-001 20040-IC13-2605-000024 APROBADO.pdf",
        )
    ]

    assert response_fabricates_documents(
        "Segun el archivo APROBADO.pdf, la referencia 20040-IC13-2605-000024 "
        "esta aprobada por 121,00 EUR.",
        items,
    ) is False


def test_fabrication_accepts_filename_suffix_from_source_path():
    items = [
        ContextItem(
            title="253434.xlsx",
            summary="Presupuesto 253434 por 121,00 EUR",
            document_filename="ALEJANDRA COMPANY LASERE/Presupuesto 260074/EXCEL/253434.xlsx",
            source_path="ALEJANDRA COMPANY LASERE/Presupuesto 260074/EXCEL/253434.xlsx",
        )
    ]

    assert response_fabricates_documents(
        "Segun 260074/EXCEL/253434.xlsx el presupuesto asciende a 121,00 EUR.",
        items,
    ) is False


# ---------------------------------------------------------------------------
# Item 8 - hardcoded confidence: not changed, but documented
# ---------------------------------------------------------------------------


def test_regex_fallback_confidence_has_explanatory_comment():
    """The regex-fallback 0.82 constant must now carry a comment
    that explains it is a placeholder pending calibration."""
    from app.services import business_extraction

    source = Path(business_extraction.__file__).read_text(encoding="utf-8")
    # The constant is still 0.82 - unchanged, as the brief says
    # "needs data-driven calibration".
    assert "confidence=0.82" in source
    # But the surrounding block now documents the rationale.
    assert "calibrate against a labelled sample" in source.lower()


# ---------------------------------------------------------------------------
# Item 9 - date utility consolidation
# ---------------------------------------------------------------------------


def test_parse_spanish_date_numeric_form():
    assert parse_spanish_date("15/06/2026") == date(2026, 6, 15)
    assert parse_spanish_date("15-06-2026") == date(2026, 6, 15)
    assert parse_spanish_date("15-06-26") == date(2026, 6, 15)


def test_parse_spanish_date_textual_form():
    assert parse_spanish_date("15 de junio de 2026") == date(2026, 6, 15)
    assert parse_spanish_date("15 jun 2026") == date(2026, 6, 15)
    assert parse_spanish_date("1 de enero de 2025") == date(2025, 1, 1)


def test_parse_spanish_date_invalid_returns_none():
    assert parse_spanish_date("") is None
    assert parse_spanish_date("32/13/2026") is None
    assert parse_spanish_date("not a date") is None


def test_quality_uses_shared_date_helper():
    """quality module must use the shared date helper from
    app.services.dates so textual Spanish dates (e.g. "15 de junio de
    2026") are recognised — not just numeric DD/MM/YYYY. The old
    ``_DATE_PATTERN`` attribute was removed when quality switched to
    ``find_dates_in_text``."""
    from app.services import quality, dates

    # quality must delegate to the shared helper, not its own regex.
    assert quality.find_dates_in_text is dates.find_dates_in_text

    # A textual Spanish date must be recognised so an invoice that uses
    # this format is no longer flagged as ``invoice_date_missing``.
    assert find_dates_in_text("Fecha: 15 de junio de 2026")


def test_business_extraction_textual_date_round_trip():
    """A document that writes its date as text must now extract it."""
    text = """
    PRESUPUESTO 2026/143
    Cliente: Talleres Norte SL
    Fecha: 12 de junio de 2026
    Total presupuesto: 330,90 EUR
    """
    result = extract_budget(document_id=1, text=text, document_confidence=0.9)
    assert result is not None
    assert result.date == date(2026, 6, 12)


def test_business_extraction_backwards_compatible_alias():
    """``_parse_date`` must still exist and accept the same inputs
    so existing callers keep working."""
    assert _parse_date("15/06/2026") == date(2026, 6, 15)


def test_find_dates_in_text_returns_all_occurrences():
    dates = find_dates_in_text(
        "Fechas: 1 de enero de 2025, 15/06/2026 y 3 mar 2024."
    )
    assert date(2025, 1, 1) in dates
    assert date(2026, 6, 15) in dates
    assert date(2024, 3, 3) in dates


def test_first_date_in_text_prefers_labelled_date():
    """When a labelled date and an unlabelled one both exist, the
    labelled one wins."""
    text = "Emision: 5 de enero de 2026. Vencimiento: 30/06/2026."
    parsed = first_date_in_text(text, preferred=["vencimiento"])
    assert parsed == date(2026, 6, 30)


# ---------------------------------------------------------------------------
# Item 10 - .doc/.docx policy
# ---------------------------------------------------------------------------


def test_doc_and_docx_not_in_blocked_list():
    """.doc and .docx must not be blocked; the router has parsers
    for both, so the block list must agree."""
    assert ".doc" not in BLOCKED_OFFICE_EXTENSIONS
    assert ".docx" not in BLOCKED_OFFICE_EXTENSIONS


def test_doc_inspection_is_allowed(tmp_path):
    """A .doc file with a real OLE signature must pass inspection."""
    target = tmp_path / "demo.doc"
    target.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest")
    result = inspect_file_for_ingestion(target)
    assert result.allowed is True
    assert result.quarantined is False


def test_docx_inspection_is_allowed(tmp_path):
    target = tmp_path / "demo.docx"
    target.write_bytes(b"PK\x03\x04rest")
    result = inspect_file_for_ingestion(target)
    assert result.allowed is True
    assert result.quarantined is False


def test_macro_enabled_still_blocked(tmp_path):
    """.docm is still blocked - that is the actual risky format."""
    assert ".docm" in BLOCKED_OFFICE_EXTENSIONS
    target = tmp_path / "demo.docm"
    target.write_bytes(b"PK\x03\x04rest")
    result = inspect_file_for_ingestion(target)
    assert result.allowed is False
    assert result.reason == "office_document_blocked"


# ---------------------------------------------------------------------------
# Item 11 - business_extraction consumes table blocks
# ---------------------------------------------------------------------------


def test_has_table_blocks_true_when_present():
    page = ExtractedPage(
        page_number=1, text="", blocks=[
            ExtractedBlock("table", "| a | b |", 1, bbox=None, confidence=0.9),
        ]
    )
    assert _has_table_blocks([page]) is True


def test_has_table_blocks_false_for_text_only():
    page = ExtractedPage(
        page_number=1, text="", blocks=[
            ExtractedBlock("text", "hello", 1, bbox=None, confidence=0.9),
        ]
    )
    assert _has_table_blocks([page]) is False


def test_has_table_blocks_false_when_none():
    assert _has_table_blocks(None) is False


def test_parse_markdown_table_basic():
    md = """
| Referencia | Descripcion | Cant | Total |
| --- | --- | --- | --- |
| REF-001 | Encimera | 2 | 241,00 |
| ABC123 | Fregadero | 1 | 89,90 |
"""
    lines = _parse_markdown_table(md)
    assert len(lines) == 2
    assert lines[0].reference == "REF-001"
    assert lines[0].description == "Encimera"
    assert lines[0].quantity == 2.0
    assert lines[0].total_price == 241.0
    assert lines[0].confidence == 0.90
    assert lines[1].reference == "ABC123"
    assert lines[1].total_price == 89.9


def test_parse_markdown_table_handles_extra_columns():
    md = """
| Ref | Desc | Cant | Precio | Total |
| --- | --- | --- | --- | --- |
| R1 | Item | 3 | 10,00 | 30,00 |
"""
    lines = _parse_markdown_table(md)
    assert len(lines) == 1
    assert lines[0].reference == "R1"
    assert lines[0].quantity == 3.0
    assert lines[0].unit_price == 10.0
    assert lines[0].total_price == 30.0


def test_extract_lines_for_document_prefers_table_block():
    """A document whose pages carry a ``block_type='table'`` block
    must be parsed via the structured table path, even if the page
    text would also match the regex."""
    md = """
| Ref | Desc | Cant | Total |
| --- | --- | --- | --- |
| REF-T | Encimera vision | 5 | 500,00 |
"""
    page = ExtractedPage(
        page_number=1,
        # The legacy regex would *also* match this line, but the
        # structured path must win because the block is table-typed.
        text="REF-T Encimera vision 5 ud 100,00 500,00",
        blocks=[
            ExtractedBlock("table", md, 1, bbox=None, confidence=0.9),
        ],
    )
    lines = _extract_lines_for_document(page.text, pages=[page])
    assert len(lines) == 1
    assert lines[0].reference == "REF-T"
    assert lines[0].description == "Encimera vision"
    # The structured path's confidence is the 0.90 placeholder,
    # not the 0.82 regex fallback.
    assert lines[0].confidence == 0.90


def test_extract_lines_for_document_falls_back_to_text_only():
    """A page with no table block and no bboxes must still fall
    back to the legacy regex path."""
    text = "REF-001 Encimera 2 ud 120,50 241,00"
    lines = _extract_lines_for_document(text, pages=None)
    assert len(lines) == 1
    assert lines[0].reference == "REF-001"
