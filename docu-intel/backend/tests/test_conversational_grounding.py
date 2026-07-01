"""CTX-10 — Conversational grounding tests.

The 9 cases the user listed in the task brief, plus a handful of
helper unit tests that pin the contract of every new module:

* :mod:`app.ai.active_context` — session state round-trip.
* :mod:`app.ai.reference_resolver` — follow-up rewrites.
* :mod:`app.ai.scope_guard` — scope pinning + global intent.
* :mod:`app.ai.intent_router` — heuristic classifier.
* :mod:`app.ai.confidence_gates` — gate evaluation + safe fallback.
* :mod:`app.ai.context` — friendly fallback (CTX-7).

DB-touching tests use an in-memory SQLite session (same pattern as
``test_feedback_loop.py`` / ``test_business_extraction.py``). The
pure-helper tests do not need a DB and run in microseconds.
"""
from __future__ import annotations

import json
from datetime import date

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_session():
    """Spin up an in-memory SQLite session with the minimal schema
    the conversational-grounding tests need.

    SQLite is incompatible with the PostgreSQL-only ``Computed``
    column on ``DocumentChunk.tsv`` (``to_tsvector``) and the
    pgvector-only ``Vector(768)`` column. Creating only the tables
    the structured-tools tests touch sidesteps both problems.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database.base import Base
    from app.models import Budget, BudgetLine, Document, Invoice, Order, OrderLine

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Document.__table__,
            Budget.__table__,
            BudgetLine.__table__,
            Order.__table__,
            OrderLine.__table__,
            Invoice.__table__,
        ],
    )
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return engine, SessionLocal


def _make_document(
    db,
    *,
    filename: str,
    document_type: str = "desconocido",
    status: str = "processed_ok",
    confidence: float | None = 0.9,
    source_path: str = "/data/input/presupuestos/260009/PDF/test.pdf",
    page_count: int = 1,
):
    from app.models import Document

    doc = Document(
        original_filename=filename,
        stored_filename=filename,
        source_path=source_path,
        file_hash=filename,
        mime_type="application/pdf",
        extension=".pdf",
        file_size=10,
        document_type=document_type,
        status=status,
        confidence=confidence,
        page_count=page_count,
    )
    db.add(doc)
    db.flush()
    return doc


# ---------------------------------------------------------------------------
# CTX-2: ActiveContext round-trip
# ---------------------------------------------------------------------------


def test_active_context_roundtrip_preserves_fields():
    from app.ai.active_context import ActiveContext

    ctx = ActiveContext(
        current_budget_number="260009",
        current_client_name="ALEJANDRA COMPANY LASERE",
        current_folder_path="/srv/x/Presupuesto 260009/",
    )
    payload = ctx.to_dict()
    restored = ActiveContext.from_dict(payload)
    assert restored.current_budget_number == "260009"
    assert restored.current_client_name == "ALEJANDRA COMPANY LASERE"
    assert restored.current_folder_path == "/srv/x/Presupuesto 260009/"


def test_active_context_drops_unknown_keys_silently():
    from app.ai.active_context import ActiveContext

    payload = {
        "current_budget_number": "260009",
        "unknown_key": "should be dropped",
    }
    ctx = ActiveContext.from_dict(payload)
    assert ctx.current_budget_number == "260009"
    # We can't access the unknown key (it's not on the dataclass),
    # but the from_dict call must not raise.


def test_active_context_scope_filters_emits_source_path_like():
    from app.ai.active_context import ActiveContext

    ctx = ActiveContext(current_budget_number="260009")
    filters = ctx.scope_filters()
    assert "source_path_like" in filters
    assert "Presupuesto 260009" in filters["source_path_like"]


# ---------------------------------------------------------------------------
# CTX-3: Reference resolver
# ---------------------------------------------------------------------------


def test_resolve_references_este_presupuesto_pins_to_active_budget():
    from app.ai.active_context import ActiveContext
    from app.ai.reference_resolver import resolve_references

    state = ActiveContext(
        current_budget_number="260009",
        current_client_name="ALEJANDRA COMPANY LASERE",
    )
    question, resolution = resolve_references(
        "por cuanto esta presupuestado", state
    )
    assert resolution.rewrote is True
    assert resolution.budget_number == "260009"
    assert resolution.referenced_entity == "budget"
    assert "260009" in question
    assert "ALEJANDRA" in question


def test_resolve_references_no_active_state_returns_noop():
    from app.ai.active_context import ActiveContext
    from app.ai.reference_resolver import resolve_references

    state = ActiveContext()
    question, resolution = resolve_references("por cuanto esta presupuestado", state)
    assert resolution.rewrote is False
    assert resolution.referenced_entity == "none"
    assert question == "por cuanto esta presupuestado"


def test_resolve_references_handles_invoice_follow_up():
    from app.ai.active_context import ActiveContext
    from app.ai.reference_resolver import resolve_references

    state = ActiveContext(current_invoice_number="F-200")
    question, resolution = resolve_references(
        "que pedido origino esta factura", state
    )
    # The question pattern matches "order" but the state has the
    # invoice number — the resolver must inject the invoice number
    # into the rewritten question so the LLM can look up the origin.
    assert resolution.rewrote is True
    assert "F-200" in question
    # The resolution should carry the invoice number so downstream
    # tools can use it.
    assert resolution.invoice_number == "F-200"


def test_resolve_references_handles_delivery_note_follow_up():
    from app.ai.active_context import ActiveContext
    from app.ai.reference_resolver import resolve_references

    state = ActiveContext(current_folder_path="/srv/x/Presupuesto 260009/")
    question, resolution = resolve_references("dispones del albaran de entrega", state)
    assert resolution.referenced_entity == "delivery_note"
    assert "Presupuesto 260009" in question


# ---------------------------------------------------------------------------
# CTX-4: Scope guard
# ---------------------------------------------------------------------------


def test_scope_guard_pins_hybrid_search_to_active_budget():
    from app.ai.active_context import ActiveContext
    from app.ai.scope_guard import enforce_budget_scope
    from app.ai.tools import ToolCall

    state = ActiveContext(current_budget_number="260009")
    tools = [ToolCall("hybrid_search", {"query": "albaran", "filters": {"limit": 5}})]
    out = enforce_budget_scope(
        question="dispones del albaran de entrega", state=state, tools=tools
    )
    assert out.scope_pinned is True
    assert out.tools[0].arguments["filters"]["source_path_like"] == "%Presupuesto 260009%"


def test_scope_guard_allows_global_when_user_asks_for_todos():
    from app.ai.active_context import ActiveContext
    from app.ai.scope_guard import enforce_budget_scope
    from app.ai.tools import ToolCall

    state = ActiveContext(current_budget_number="260009")
    tools = [ToolCall("hybrid_search", {"query": "albaran", "filters": {"limit": 5}})]
    out = enforce_budget_scope(
        question="busca en todos los presupuestos", state=state, tools=tools
    )
    assert out.scope_pinned is False
    assert out.global_intent is True
    # Tools must NOT have the scope filter applied.
    assert "source_path_like" not in out.tools[0].arguments["filters"]


def test_scope_guard_no_active_state_keeps_tools_untouched():
    from app.ai.active_context import ActiveContext
    from app.ai.scope_guard import enforce_budget_scope
    from app.ai.tools import ToolCall

    state = ActiveContext()
    tools = [ToolCall("hybrid_search", {"query": "albaran", "filters": {"limit": 5}})]
    out = enforce_budget_scope(question="dispones del albaran", state=state, tools=tools)
    assert out.scope_pinned is False
    assert "source_path_like" not in out.tools[0].arguments.get("filters", {})


def test_scope_guard_pins_get_budget_by_number_when_missing():
    from app.ai.active_context import ActiveContext
    from app.ai.scope_guard import enforce_budget_scope
    from app.ai.tools import ToolCall

    state = ActiveContext(current_budget_number="260009")
    tools = [ToolCall("get_budget_by_number", {})]
    out = enforce_budget_scope(
        question="importe total del presupuesto", state=state, tools=tools
    )
    assert out.tools[0].arguments["budget_number"] == "260009"


def test_scope_guard_does_not_override_explicit_budget_number():
    from app.ai.active_context import ActiveContext
    from app.ai.scope_guard import enforce_budget_scope
    from app.ai.tools import ToolCall

    state = ActiveContext(current_budget_number="260009")
    tools = [ToolCall("get_budget_by_number", {"budget_number": "260011"})]
    out = enforce_budget_scope(
        question="de que trata el presupuesto 260011", state=state, tools=tools
    )
    # The user named a different budget; the scope guard must NOT
    # overwrite it.
    assert out.tools[0].arguments["budget_number"] == "260011"


def test_collect_context_falls_back_to_budget_document_filename(monkeypatch):
    from app.ai.context import collect_context
    from app.ai.tools import ToolCall
    from app.tools import internal

    class Doc:
        id = 110
        original_filename = "ALEJANDRA/Presupuesto 260074/EXCEL/253434.xlsx"
        source_path = "ALEJANDRA/Presupuesto 260074/EXCEL/253434.xlsx"
        document_type = "presupuesto"
        status = "needs_review"
        confidence = 0.82
        page_count = 1

    monkeypatch.setattr(internal, "get_budget_by_number", lambda db, number: None)
    monkeypatch.setattr(internal, "find_document_by_filename", lambda db, query: [Doc()])

    context, warnings, resolved_doc_id = collect_context(
        object(),
        [ToolCall("get_budget_by_number", {"budget_number": "253434"})],
        "de que trata el presupuesto 253434",
    )

    assert resolved_doc_id == 110
    assert context[0].document_id == 110
    assert "253434.xlsx" in context[0].source_path
    assert "no esta en la tabla estructurada" in warnings[0]


# ---------------------------------------------------------------------------
# CTX-5: Intent router
# ---------------------------------------------------------------------------


def test_intent_router_classifies_accepted_budgets():
    from app.ai.intent_router import INTENT_ACCEPTED_BUDGETS, classify_intent

    cls = classify_intent("ultimos presupuestos aceptados")
    assert cls.intent == INTENT_ACCEPTED_BUDGETS


def test_intent_router_classifies_budget_total_with_followup():
    from app.ai.active_context import ActiveContext
    from app.ai.intent_router import INTENT_BUDGET_TOTAL, classify_intent

    state = ActiveContext(current_budget_number="260009")
    cls = classify_intent("por cuanto esta presupuestado", state)
    assert cls.intent == INTENT_BUDGET_TOTAL
    assert cls.needs_state is False  # state supplied


def test_intent_router_flags_needs_state_when_state_is_empty():
    from app.ai.intent_router import INTENT_BUDGET_TOTAL, classify_intent

    cls = classify_intent("por cuanto esta presupuestado")
    assert cls.intent == INTENT_BUDGET_TOTAL
    assert cls.needs_state is True


def test_intent_router_classifies_delivery_note_lookup():
    from app.ai.active_context import ActiveContext
    from app.ai.intent_router import INTENT_DELIVERY_NOTE, classify_intent

    state = ActiveContext(current_folder_path="/srv/x/Presupuesto 260009/")
    cls = classify_intent("dispones del albaran de entrega", state)
    assert cls.intent == INTENT_DELIVERY_NOTE


def test_intent_router_classifies_invoice_origin_order():
    from app.ai.intent_router import INTENT_INVOICE_ORIGIN_ORDER, classify_intent

    cls = classify_intent("que pedido origino esta factura")
    assert cls.intent == INTENT_INVOICE_ORIGIN_ORDER


# ---------------------------------------------------------------------------
# CTX-6: Structured tools
# ---------------------------------------------------------------------------


def test_structured_tool_selection_for_budget_total_with_state():
    from app.ai.active_context import ActiveContext
    from app.ai.tools import select_structured_tools

    state = ActiveContext(current_budget_number="260009")
    tools = select_structured_tools("por cuanto esta presupuestado", active_context=state)
    assert [t.name for t in tools] == ["get_budget_total"]
    assert tools[0].arguments["budget_number"] == "260009"


def test_structured_tool_selection_for_delivery_note():
    from app.ai.active_context import ActiveContext
    from app.ai.tools import select_structured_tools

    state = ActiveContext(
        current_budget_number="260009",
        current_folder_path="/srv/x/Presupuesto 260009/",
    )
    tools = select_structured_tools("dispones del albaran de entrega", active_context=state)
    assert [t.name for t in tools] == ["find_delivery_note_in_scope"]


def test_structured_tool_selection_for_accepted_budgets_has_no_state_dependency():
    from app.ai.tools import select_structured_tools

    tools = select_structured_tools("ultimos presupuestos aceptados")
    assert [t.name for t in tools] == ["list_recent_accepted_budgets"]


def test_get_budget_total_returns_found_with_amount(db_session_like):
    from app.models import Budget
    from app.tools.internal import get_budget_total

    _, SessionLocal = db_session_like
    with SessionLocal() as db:
        document = _make_document(db, filename="pres_260009.pdf", document_type="presupuesto")
        budget = Budget(
            document_id=document.id,
            budget_number="260009",
            client_name="ALEJANDRA",
            date=date(2026, 6, 1),
            total_amount=1234.56,
            currency="EUR",
            status="aceptado",
            accepted_detected=True,
            confidence=0.9,
            budget_number_normalized="260009",
        )
        db.add(budget)
        db.commit()

        result = get_budget_total(db, budget_number="260009")
    assert result["found"] is True
    assert result["total_amount"] == 1234.56
    assert result["currency"] == "EUR"
    assert result["accepted"] is True


def test_get_invoiced_amount_sums_invoices_for_budget_orders(db_session_like):
    from app.models import Budget, Invoice, Order
    from app.tools.internal import get_invoiced_amount_for_budget

    _, SessionLocal = db_session_like
    with SessionLocal() as db:
        document = _make_document(db, filename="pres_260009.pdf", document_type="presupuesto")
        budget = Budget(
            document_id=document.id,
            budget_number="260009",
            budget_number_normalized="260009",
            date=date(2026, 6, 1),
            total_amount=1000.0,
        )
        db.add(budget)
        db.flush()
        order = Order(
            document_id=document.id,
            order_number="P-100",
            order_number_normalized="p100",
            related_budget_id=budget.id,
            date=date(2026, 6, 2),
            total_amount=1000.0,
        )
        db.add(order)
        db.flush()
        invoice = Invoice(
            document_id=document.id,
            invoice_number="F-1",
            related_order_id=order.id,
            total_amount=500.0,
            date=date(2026, 5, 1),
        )
        db.add(invoice)
        db.commit()

        result = get_invoiced_amount_for_budget(db, budget_number="260009")
    assert result["found"] is True
    assert result["invoiced"] == 500.0
    assert result["invoice_count"] == 1
    assert result["order_count"] == 1


def test_find_delivery_note_in_scope_refuses_when_no_scope():
    from app.tools.internal import find_delivery_note_in_scope

    _, SessionLocal = _make_db_session()
    with SessionLocal() as db:
        result = find_delivery_note_in_scope(db)
    assert result["found"] is False
    assert "no se ha indicado ambito" in result["reason"]


def test_find_delivery_note_in_scope_filters_by_source_path(db_session_like):
    from app.models import Document
    from app.tools.internal import find_delivery_note_in_scope

    _, SessionLocal = db_session_like
    with SessionLocal() as db:
        _make_document(
            db,
            filename="albaran_260009.pdf",
            document_type="albaran",
            source_path="/data/input/presupuestos/Presupuesto 260009/albaran_260009.pdf",
        )
        _make_document(
            db,
            filename="albaran_260011.pdf",
            document_type="albaran",
            source_path="/data/input/presupuestos/Presupuesto 260011/albaran_260011.pdf",
        )
        db.commit()
        result = find_delivery_note_in_scope(db, budget_number="260009")
    assert result["found"] is True
    assert len(result["matches"]) == 1
    assert "260009" in result["matches"][0]["filename"]


# ---------------------------------------------------------------------------
# CTX-7: Friendly grounded fallback
# ---------------------------------------------------------------------------


def test_friendly_fallback_for_duplicate_document_uses_business_language():
    from app.ai.context import ContextItem, build_grounded_response

    items = [
        ContextItem(
            title="Documento: VISTA ALEGRE carpinteria.pdf",
            summary=(
                "Tipo: desconocido | Estado: duplicate | Confianza: None | "
                "Paginas: None | Ruta: /data/input/presupuestos/Presupuesto "
                "260009/PDF/VISTA ALEGRE carpinteria.pdf"
            ),
            document_id=1,
            document_filename="VISTA ALEGRE carpinteria.pdf",
            confidence=None,
            source_path="/data/input/presupuestos/Presupuesto 260009/PDF/VISTA ALEGRE carpinteria.pdf",
        ),
        ContextItem(
            title="Plano principal",
            summary="Otro plano del mismo proyecto",
            document_id=2,
            document_filename="VISTA ALEGRE planta.pdf",
        ),
    ]
    gr = build_grounded_response(
        question="de que trata el plano VISTA ALEGRE carpinteria.pdf",
        context_items=items,
        warnings=[],
    )
    answer = gr.answer.lower()
    assert "confianza none" not in answer
    assert "estado: duplicate" not in answer
    assert "duplicado" in answer
    assert "no tiene" in answer or "sin extraccion" in answer or "recomiendo" in answer


def test_friendly_fallback_for_unknown_type_suggests_reprocess():
    from app.ai.context import ContextItem, build_grounded_response

    items = [
        ContextItem(
            title="Documento: foo.pdf",
            summary="Tipo: desconocido | Estado: processed_ok | Confianza: 0.9 | Paginas: 2",
            document_id=1,
            document_filename="foo.pdf",
            confidence=0.9,
        )
    ]
    gr = build_grounded_response(question="de que trata foo.pdf", context_items=items, warnings=[])
    assert "desconocido" in gr.answer.lower() or "clasificado" in gr.answer.lower()
    assert "re-proces" in gr.answer.lower() or "reproces" in gr.answer.lower()


def test_friendly_fallback_for_low_ocr_warns_and_suggests_reprocess():
    from app.ai.context import ContextItem, build_grounded_response

    items = [
        ContextItem(
            title="Documento: bar.pdf",
            summary="Tipo: presupuesto | Estado: processed_ok | Confianza: 0.55 | Paginas: 3",
            document_id=1,
            document_filename="bar.pdf",
            confidence=0.55,
        )
    ]
    gr = build_grounded_response(question="que dice bar.pdf", context_items=items, warnings=[])
    assert "baja" in gr.answer.lower()
    assert "no puedo" in gr.answer.lower() or "recomiendo" in gr.answer.lower()


# ---------------------------------------------------------------------------
# CTX-8: Confidence gates
# ---------------------------------------------------------------------------


def test_confidence_gate_blocks_amount_when_ocr_is_low():
    from app.ai.confidence_gates import evaluate_confidence_gates
    from app.ai.context import ContextItem

    items = [
        ContextItem(
            title="Presupuesto 260009",
            summary="Total 1234,56 EUR",
            document_id=1,
            document_filename="pres.pdf",
            confidence=0.55,
            ocr_confidence=0.55,
            excerpt="Importe total 1.234,56 EUR",
        )
    ]
    ev = evaluate_confidence_gates(
        question="por cuanto esta presupuestado", context_items=items
    )
    assert ev.requires_amount is True
    assert ev.is_blocked is True
    assert "ocr_baja_confianza" in ev.gates_open


def test_confidence_gate_does_not_block_non_amount_questions():
    from app.ai.confidence_gates import evaluate_confidence_gates
    from app.ai.context import ContextItem

    items = [
        ContextItem(
            title="Plano",
            summary="Plano planta",
            document_id=1,
            document_filename="plan.pdf",
            confidence=0.55,
        )
    ]
    ev = evaluate_confidence_gates(
        question="de que trata el plano plan.pdf", context_items=items
    )
    # Plan summaries are not amount questions: the gate stays advisory.
    assert ev.requires_amount is False
    assert ev.is_blocked is False


def test_confidence_gate_extracts_amount_candidates():
    from app.ai.confidence_gates import evaluate_confidence_gates
    from app.ai.context import ContextItem

    items = [
        ContextItem(
            title="Doc",
            summary="Varios importes",
            document_id=1,
            document_filename="doc.pdf",
            confidence=0.55,
            ocr_confidence=0.55,
            excerpt=(
                "Importe total 1.234,56 EUR Base imponible 1.000,00 EUR "
                "IVA 21% 210,00 EUR Envio portes 25,00 EUR "
                "Total factura 1.459,56 EUR"
            ),
        )
    ]
    ev = evaluate_confidence_gates(
        question="por cuanto esta presupuestado", context_items=items
    )
    assert ev.is_blocked is True
    assert len(ev.amount_candidates) >= 2


def test_confidence_gate_duplicate_status_blocks():
    from app.ai.confidence_gates import evaluate_confidence_gates
    from app.ai.context import ContextItem

    items = [
        ContextItem(
            title="Doc",
            summary="Texto",
            document_id=1,
            document_filename="doc.pdf",
            confidence=0.9,
        )
    ]
    ev = evaluate_confidence_gates(
        question="por cuanto esta presupuestado",
        context_items=items,
        resolved_document={
            "id": 1,
            "status": "duplicate",
            "document_type": "presupuesto",
        },
    )
    assert "documento_duplicado" in ev.gates_open


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session_like():
    """A pair of (engine, SessionLocal) for tests that need a real DB."""
    return _make_db_session()
