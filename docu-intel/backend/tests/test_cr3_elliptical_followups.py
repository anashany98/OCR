"""CR3 — Tests for elliptical follow-up detection.

Verifies that short questions like "¿De qué fecha es?" are detected
as follow-ups and resolved to the active document context.
"""

from __future__ import annotations

import pytest

from app.ai.active_context import ActiveContext
from app.ai.reference_resolver import detect_reference, resolve_references


def test_de_que_fecha_es_detected():
    kind, key = detect_reference("¿De qué fecha es?")
    assert kind == "document"
    assert key == "current_document_id"


def test_que_importe_tiene_detected():
    kind, key = detect_reference("¿Qué importe tiene?")
    assert kind == "document"
    assert key == "current_document_id"


def test_quien_lo_instala_detected():
    kind, key = detect_reference("¿Quién lo instala?")
    assert kind == "document"
    assert key == "current_document_id"


def test_cuantas_unidades_detected():
    kind, key = detect_reference("¿Cuántas unidades?")
    assert kind == "document"
    assert key == "current_document_id"


def test_y_el_cliente_detected():
    kind, key = detect_reference("¿Y el cliente?")
    assert kind == "document"
    assert key == "current_document_id"


def test_y_el_proveedor_detected():
    kind, key = detect_reference("¿Y el proveedor?")
    assert kind == "document"
    assert key == "current_document_id"


def test_que_direccion_tiene_detected():
    kind, key = detect_reference("¿Qué dirección tiene?")
    assert kind == "document"
    assert key == "current_document_id"


def test_que_estado_tiene_detected():
    kind, key = detect_reference("¿Qué estado tiene?")
    assert kind == "document"
    assert key == "current_document_id"


def test_explicit_reference_still_works():
    kind, key = detect_reference("¿Este presupuesto?")
    assert kind == "budget"


def test_long_question_not_detected():
    result = detect_reference("¿Cuál es el presupuesto total del proyecto 2025?")
    # This is a full question, not an elliptical follow-up
    # It should match the budget pattern
    assert result is not None
    assert result[0] == "budget"


def test_resolve_elliptical_with_document_context():
    state = ActiveContext(
        current_document_id=1249,
        current_document_path="/app/data/input/2025/ARABELLA/Presupuesto 251044/PDF/hoja.pdf",
        current_budget_number="251044",
    )
    rewritten, resolution = resolve_references("¿De qué fecha es?", state)
    assert resolution.rewrote is True
    assert "Contexto:" in rewritten
    assert "12/01/2026" not in rewritten  # should not hallucinate
    assert "documento" in rewritten.lower() or "presupuesto" in rewritten.lower()


def test_resolve_elliptical_no_context():
    state = ActiveContext()
    rewritten, resolution = resolve_references("¿De qué fecha es?", state)
    assert resolution.rewrote is False
    assert rewritten == "¿De qué fecha es?"


def test_resolve_elliptical_doc_id_only():
    """When only document_id is in context (no path), the elliptical
    follow-up should still be resolved."""
    state = ActiveContext(current_document_id=1249)
    rewritten, resolution = resolve_references("¿Qué importe tiene?", state)
    assert resolution.rewrote is True
    assert "Contexto:" in rewritten


def test_implicit_followup_with_pronoun():
    state = ActiveContext(
        current_document_id=1249,
        current_budget_number="260025",
    )
    # "De este presupuesto" matches the budget pattern
    rewritten, resolution = resolve_references("¿De este presupuesto?", state)
    assert resolution.rewrote is True
    assert "Contexto:" in rewritten
    assert "presupuesto" in rewritten.lower()
