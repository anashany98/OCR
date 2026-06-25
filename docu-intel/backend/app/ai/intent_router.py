"""CTX-5 — Business intent router.

Pure-Python heuristic that classifies a user question into one of the
business intents the agent is expected to handle. The list of intents
mirrors the task brief:

* ``accepted_budgets``           — "últimos presupuestos aceptados".
* ``budget_summary``             — "de que trata el presupuesto X".
* ``budget_total``               — "por cuanto esta presupuestado".
* ``budget_lines``               — "que lineas tiene este presupuesto".
* ``budget_status``              — "esta aceptado el presupuesto X?".
* ``invoiced_amount_for_budget`` — "cuanto se ha facturado de este presupuesto".
* ``invoice_origin_order``       — "que pedido origino esta factura".
* ``delivery_note_lookup``       — "dispones del albaran de entrega".
* ``shipping_cost_lookup``       — "cuanto costo el envio".
* ``supplier_breakdown``         — "desglosado por proveedor".
* ``time_filtered_query``        — "en el ultimo trimestre", "este ano".
* ``plan_summary``               — "de que trata el plano X".
* ``document_summary``           — "de que trata el documento X".
* ``related_documents``          — "que documentos hay relacionados".
* ``generic_document_question``  — fallback.

The classifier is rule-based (no LLM) and tested in
``tests/test_intent_router.py``. It runs BEFORE the tool selector so
the orchestrator can pin the request to a structured SQL path
(CTX-6) when an intent is recognised and the data is available.

The classifier is state-aware: when the active context already names
a budget (because the previous turn resolved one) the patterns that
implicitly point at a budget (``"por cuanto esta presupuestado"``)
match the corresponding intent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .active_context import ActiveContext
from .reference_resolver import detect_reference

# Intent identifiers (string constants — they show up in metrics + logs)
INTENT_ACCEPTED_BUDGETS = "accepted_budgets"
INTENT_BUDGET_SUMMARY = "budget_summary"
INTENT_BUDGET_TOTAL = "budget_total"
INTENT_BUDGET_LINES = "budget_lines"
INTENT_BUDGET_STATUS = "budget_status"
INTENT_INVOICED_AMOUNT = "invoiced_amount_for_budget"
INTENT_INVOICE_ORIGIN_ORDER = "invoice_origin_order"
INTENT_DELIVERY_NOTE = "delivery_note_lookup"
INTENT_SHIPPING_COST = "shipping_cost_lookup"
INTENT_SUPPLIER_BREAKDOWN = "supplier_breakdown"
INTENT_TIME_FILTERED = "time_filtered_query"
INTENT_PLAN_SUMMARY = "plan_summary"
INTENT_DOCUMENT_SUMMARY = "document_summary"
INTENT_RELATED_DOCUMENTS = "related_documents"
INTENT_GENERIC = "generic_document_question"

ALL_INTENTS: tuple[str, ...] = (
    INTENT_ACCEPTED_BUDGETS,
    INTENT_BUDGET_SUMMARY,
    INTENT_BUDGET_TOTAL,
    INTENT_BUDGET_LINES,
    INTENT_BUDGET_STATUS,
    INTENT_INVOICED_AMOUNT,
    INTENT_INVOICE_ORIGIN_ORDER,
    INTENT_DELIVERY_NOTE,
    INTENT_SHIPPING_COST,
    INTENT_SUPPLIER_BREAKDOWN,
    INTENT_TIME_FILTERED,
    INTENT_PLAN_SUMMARY,
    INTENT_DOCUMENT_SUMMARY,
    INTENT_RELATED_DOCUMENTS,
    INTENT_GENERIC,
)


@dataclass(frozen=True)
class IntentClassification:
    intent: str
    confidence: float
    reason: str
    needs_state: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "reason": self.reason,
            "needs_state": self.needs_state,
        }


# ---------------------------------------------------------------------------
# Normalisation (independent of the others so this module can be tested
# without the rest of the agent stack)
# ---------------------------------------------------------------------------


_NORMALIZE_TABLE = str.maketrans("áéíóúüñ¿¡", "aeiouun  ")


def _normalize(text: str) -> str:
    return (text or "").lower().translate(_NORMALIZE_TABLE)


# ---------------------------------------------------------------------------
# Pattern banks
# ---------------------------------------------------------------------------
# Each entry is ``(intent_id, compiled_regex, base_confidence, reason)``.
# The first matching entry wins. The order matters: specific intents
# come before generic ones.

_PATTERN_BANK: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    # --- accepted / latest budgets ---
    (
        INTENT_ACCEPTED_BUDGETS,
        re.compile(
            r"\b(ultim[oa]s?|las?\s+ultim[oa]s?|recientes?)\s+presupuestos?\s+aceptad[oa]s?\b"
        ),
        0.95,
        "ultimos presupuestos aceptados",
    ),
    (
        INTENT_ACCEPTED_BUDGETS,
        re.compile(r"\bpresupuestos?\s+aceptad[oa]s?\s+(sin|pendiente)\s+pedido\b"),
        0.95,
        "aceptados sin pedido",
    ),
    (
        INTENT_ACCEPTED_BUDGETS,
        re.compile(r"\b(cuales|que)\s+son\s+los?\s+presupuestos?\s+aceptad[oa]s?\b"),
        0.9,
        "cuales son los aceptados",
    ),
    # --- budget summary / status / total / lines ---
    (
        INTENT_BUDGET_TOTAL,
        re.compile(
            r"\b(por cuanto|cuanto|cual es el importe|cu[a]nto)\s+(esta\s+presupuestad[oa]|importa|sale|cuesta|asciende)\b"
        ),
        0.9,
        "por cuanto esta presupuestado",
    ),
    (
        INTENT_BUDGET_TOTAL,
        re.compile(r"\bimporte\s+total\s+del\s+presupuesto\b"),
        0.9,
        "importe total del presupuesto",
    ),
    (
        INTENT_BUDGET_LINES,
        re.compile(r"\b(que|cuales)\s+lineas\s+tiene\s+(este|el|ese)?\s*presupuesto\b"),
        0.9,
        "que lineas tiene este presupuesto",
    ),
    (
        INTENT_BUDGET_LINES,
        re.compile(
            r"\b(desglose|desglosa|detalle|descomponer)\s+(del|de|este|el)?\s*presupuesto\b"
        ),
        0.85,
        "desglose del presupuesto",
    ),
    (
        INTENT_BUDGET_STATUS,
        re.compile(
            r"\b(esta|se)\s+(aceptad[oa]|aprobad[oa]|rechazad[oa]|pendiente)\b.*\b(presupuesto)?\b"
        ),
        0.8,
        "estado del presupuesto",
    ),
    (
        INTENT_BUDGET_SUMMARY,
        re.compile(r"\bde\s+que\s+trata\s+(el|este|ese)\s+presupuesto\b"),
        0.9,
        "de que trata el presupuesto",
    ),
    # --- invoiced amount ---
    (
        INTENT_INVOICED_AMOUNT,
        re.compile(r"\bcuanto\s+(se\s+)?ha\s+facturad[oa]\s+(de|del|en)\b"),
        0.9,
        "cuanto se ha facturado de",
    ),
    (
        INTENT_INVOICED_AMOUNT,
        re.compile(r"\b(importe|total)\s+facturad[oa]\b"),
        0.85,
        "importe facturado",
    ),
    # --- invoice origin order ---
    (
        INTENT_INVOICE_ORIGIN_ORDER,
        re.compile(r"\bque\s+pedido\s+origino\s+(esta|la|esa)\s+factura\b"),
        0.95,
        "que pedido origino esta factura",
    ),
    (
        INTENT_INVOICE_ORIGIN_ORDER,
        re.compile(r"\bpedido\s+(origen|asociad[oa])\s+(a|de)\s+(esta|la|esa)\s+factura\b"),
        0.9,
        "pedido origen de la factura",
    ),
    # --- delivery note / shipping ---
    (
        INTENT_DELIVERY_NOTE,
        re.compile(r"\b(dispon(es|es)\s+del|hay|tienes?|existe)\s+(el|un)?\s*albaran\b"),
        0.9,
        "dispones del albaran",
    ),
    (
        INTENT_DELIVERY_NOTE,
        re.compile(r"\balbaran\s+(de\s+)?entrega\b"),
        0.85,
        "albaran de entrega",
    ),
    (
        INTENT_SHIPPING_COST,
        re.compile(r"\b(cuanto|cual)\s+(cuest[oa]|cost[oa]|es)\s+(el|lo)\s+envio\b"),
        0.9,
        "cuanto costo el envio",
    ),
    (
        INTENT_SHIPPING_COST,
        re.compile(r"\b(portes|flete|fletes|transporte|logistica|shipping)\b"),
        0.7,
        "portes / flete / transporte",
    ),
    # --- supplier breakdown / time filter ---
    (
        INTENT_SUPPLIER_BREAKDOWN,
        re.compile(
            r"\b(desglosad[oa]|desglose|agrupad[oa]|por\s+proveedor|por\s+cada\s+proveedor)\b"
        ),
        0.85,
        "desglose por proveedor",
    ),
    (
        INTENT_TIME_FILTERED,
        re.compile(
            r"\b(este\s+ano|este\s+año|ultimo\s+trimestre|ultim[oa]s?\s+\d+\s+meses?|en\s+\d{4}|del\s+ano|este\s+mes)\b"
        ),
        0.8,
        "filtro temporal",
    ),
    # --- plan / drawing ---
    (
        INTENT_PLAN_SUMMARY,
        re.compile(r"\bde\s+que\s+trata\s+(el|este|ese)\s+plano\b"),
        0.9,
        "de que trata el plano",
    ),
    (
        INTENT_PLAN_SUMMARY,
        re.compile(r"\b(este|el|ese)\s+plano\b"),
        0.7,
        "este plano",
    ),
    # --- generic document summary ---
    (
        INTENT_DOCUMENT_SUMMARY,
        re.compile(r"\bde\s+que\s+trata\s+(el|este|ese)\s+documento\b"),
        0.9,
        "de que trata el documento",
    ),
    # --- related documents ---
    (
        INTENT_RELATED_DOCUMENTS,
        re.compile(r"\b(documentos?)\s+relacionad[oa]s?\b"),
        0.85,
        "documentos relacionados",
    ),
    (
        INTENT_RELATED_DOCUMENTS,
        re.compile(r"\b(que\s+hay|que\s+tienes?)\s+(en\s+la\s+misma|relacionad[oa])\b"),
        0.8,
        "que hay en la misma carpeta",
    ),
)


# Patterns that REQUIRE an active state to make sense. The router
# emits a ``needs_state=True`` classification so the orchestrator can
# warn the user when the context is empty.
_STATE_ONLY_INTENTS: frozenset[str] = frozenset(
    {
        INTENT_BUDGET_TOTAL,
        INTENT_BUDGET_LINES,
        INTENT_BUDGET_SUMMARY,
        INTENT_BUDGET_STATUS,
        INTENT_INVOICED_AMOUNT,
        INTENT_INVOICE_ORIGIN_ORDER,
        INTENT_DELIVERY_NOTE,
        INTENT_SHIPPING_COST,
        INTENT_RELATED_DOCUMENTS,
    }
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_intent(
    question: str,
    state: ActiveContext | None = None,
) -> IntentClassification:
    """Return the intent classification for ``question``.

    The first matching pattern wins. When nothing matches, the intent
    is :data:`INTENT_GENERIC` with confidence 0.5. When the recognised
    intent requires an active context (``INTENT_BUDGET_TOTAL``,
    ``INTENT_DELIVERY_NOTE``, …) but the state is empty, the router
    flags ``needs_state=True`` so the orchestrator can warn the user
    instead of falling back silently to a global search.
    """
    text = (question or "").strip()
    if not text:
        return IntentClassification(intent=INTENT_GENERIC, confidence=0.0, reason="empty question")

    normalised = _normalize(text)
    for intent, pattern, base_conf, reason in _PATTERN_BANK:
        if pattern.search(normalised):
            return _finalize(
                intent=intent,
                confidence=base_conf,
                reason=reason,
                state=state,
            )

    # Follow-up references that did not match a specific pattern are
    # still routed to the right intent: a "este presupuesto" without
    # an explicit verb is a budget_summary; a "el albaran" is a
    # delivery_note_lookup, etc.
    reference = detect_reference(text)
    if reference is not None:
        kind, _ = reference
        inferred = _intent_from_reference_kind(kind)
        if inferred is not None:
            return _finalize(
                intent=inferred,
                confidence=0.7,
                reason=f"reference to {kind}",
                state=state,
            )

    return IntentClassification(
        intent=INTENT_GENERIC, confidence=0.5, reason="no specific pattern matched"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finalize(
    *,
    intent: str,
    confidence: float,
    reason: str,
    state: ActiveContext | None,
) -> IntentClassification:
    if state is None or not _has_state_for(intent, state):
        return IntentClassification(
            intent=intent,
            confidence=confidence,
            reason=reason,
            needs_state=intent in _STATE_ONLY_INTENTS,
        )
    return IntentClassification(
        intent=intent,
        confidence=confidence,
        reason=reason,
        needs_state=False,
    )


def _has_state_for(intent: str, state: ActiveContext) -> bool:
    """True when the active context carries the entity the intent needs."""
    if intent in {
        INTENT_BUDGET_TOTAL,
        INTENT_BUDGET_LINES,
        INTENT_BUDGET_SUMMARY,
        INTENT_BUDGET_STATUS,
        INTENT_INVOICED_AMOUNT,
    }:
        return bool(state.current_budget_number or state.current_budget_id)
    if intent == INTENT_INVOICE_ORIGIN_ORDER:
        return bool(state.current_invoice_number or state.current_order_number)
    if intent == INTENT_DELIVERY_NOTE:
        return bool(
            state.has_budget_scope
            or state.current_delivery_note_number
            or state.current_folder_path
        )
    if intent == INTENT_SHIPPING_COST:
        return bool(state.has_budget_scope or state.current_folder_path)
    if intent == INTENT_RELATED_DOCUMENTS:
        return bool(
            state.current_document_id or state.has_budget_scope or state.current_folder_path
        )
    return True


def _intent_from_reference_kind(kind: str) -> str | None:
    if kind == "budget":
        return INTENT_BUDGET_SUMMARY
    if kind == "order":
        return INTENT_DOCUMENT_SUMMARY
    if kind == "invoice":
        return INTENT_INVOICE_ORIGIN_ORDER
    if kind == "delivery_note":
        return INTENT_DELIVERY_NOTE
    if kind == "plan":
        return INTENT_PLAN_SUMMARY
    if kind == "document":
        return INTENT_DOCUMENT_SUMMARY
    if kind == "folder":
        return INTENT_RELATED_DOCUMENTS
    return None
