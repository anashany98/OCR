"""Tool selection and classification helpers for the AI agent.

This module owns the **decision of which backend tool(s) to call**
for a given user question. It does not call the tools — that is
the orchestrator's job (see ``app.ai.context.collect_context``).

The classifier is intentionally rule-based rather than ML. We have
a fixed tool surface (15 internal tools) and a small, well-known
question grammar ("dame el presupuesto N", "cuanto nos hemos gastado
en X"). Rules are easier to test, easier to extend, and they fail
loudly when a new question type is not covered (vs. a model that
silently picks the wrong tool).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

# Re-exported so other code in the project that imports
# ``app.ai.agent._money_filters`` still works (this is the alias the
# original agent.py used).
from app.tools.internal import _money_filters  # noqa: F401


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    """A single tool call the orchestrator should execute.

    ``name`` is one of the tool identifiers registered in
    ``app.tools.internal`` (e.g. ``hybrid_search``,
    ``get_budget_by_number``, ``aggregate_business``).

    ``arguments`` is a free-form dict whose shape is documented
    in the tool's implementation. We keep this typed as ``dict``
    rather than per-tool TypedDict because the surface keeps
    growing and a single schema would be a maintenance hazard.
    """

    name: str
    arguments: dict[str, Any]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def select_tools_for_question(question: str) -> list[ToolCall]:
    """Pick the right set of internal tools for ``question``.

    Returns a list because some question types (a budget number +
    a fuzzy content match) legitimately need more than one tool
    chained. The list is ordered: tools earlier in the list are
    expected to be the primary source of context; later tools
    are fallback / enrichment.

    The decision tree:

    1. **Aggregation** ("cuanto", "total", "suma", "facturado" ...)
       -> ``aggregate_business`` + ``hybrid_search`` (for citations).
    2. **Filename mention** -> ``find_document_by_filename`` +
       placeholder slots for full details and related docs (the
       orchestrator rewrites the placeholders after the lookup).
    3. **Document number** + entity type -> ``get_budget_by_number``
       / ``get_order_by_number`` + same placeholders.
    4. **Catch-all patterns** ("presupuestos aceptados sin pedido",
       "ultimo pedido", "duplicados", "baja confianza", entities,
       plan rooms, planos in general) -> single-tool call.
    5. **Fallback** -> ``hybrid_search`` with whatever relevance
       filters we can infer from the question (supplier, client,
       amount range).
    """
    normalized = _normalize(question)
    document_number = _extract_document_number(question)

    # ---- Aggregation intent (SQL over structured tables) ----
    # Catches the "cuanto nos hemos gastado en X", "cuantos pedidos sin
    # factura" family of questions that cannot be answered with text search.
    if _is_aggregation_question(normalized):
        entity, kind = _classify_aggregation(normalized)
        tools: list[ToolCall] = [ToolCall("aggregate_business", {"entity": entity, "kind": kind})]
        # Also pull the top documents that match, so the LLM can cite them.
        tools.append(ToolCall("hybrid_search", {"query": question, "filters": {"limit": 4}}))
        return tools

    # ---- Specific file mentioned -> lookup + details + relations ----
    # If the user mentions a filename (with extension) we use the lookup path
    # so the LLM gets the document's entities and its connections to the
    # rest of the project, not just text snippets.
    mentioned_filenames = _extract_filenames(question)
    if mentioned_filenames:
        tools = [
            ToolCall("find_document_by_filename", {"query": mentioned_filenames[0]}),
            ToolCall("get_document_full_details", {"document_id": 0}),  # placeholder; replaced after lookup
            ToolCall("get_related_documents", {"document_id": 0}),  # placeholder; replaced after lookup
        ]
        # Always run a hybrid search too in case the user asks for content
        # not covered by the entities (e.g. a specific page or paragraph).
        search_filters: dict = {"limit": 6}
        _maybe_apply_relevance_filter(search_filters, normalized, question)
        tools.append(ToolCall("hybrid_search", {"query": question, "filters": search_filters}))
        return tools

    # ---- Presupuesto / pedido / factura by number -> details + relations ----
    # If the user mentions a number and references a document concept
    # (presupuesto, pedido, factura, etc.), use the same smart chain.
    if document_number and (
        "presupuest" in normalized
        or "pedido" in normalized
        or "factura" in normalized
        or "documento" in normalized
    ):
        # Prefer presupuesto when the user names it explicitly; otherwise
        # fall back to pedido. This avoids searching by pedido number when
        # the user actually asked about the budget.
        if "presupuest" in normalized:
            primary = ToolCall("get_budget_by_number", {"budget_number": document_number})
        elif "pedido" in normalized:
            primary = ToolCall("get_order_by_number", {"order_number": document_number})
        else:
            primary = ToolCall("get_budget_by_number", {"budget_number": document_number})
        return [
            primary,
            ToolCall("get_document_full_details", {"document_id": 0}),
            ToolCall("get_related_documents", {"document_id": 0}),
            ToolCall("hybrid_search", {"query": question, "filters": {"limit": 6}}),
        ]

    if "presupuest" in normalized and "acept" in normalized and ("sin pedido" in normalized or "no tienen pedido" in normalized):
        return [ToolCall("get_accepted_budgets_without_order", {})]
    if "linea" in normalized and "pedido" in normalized:
        return [ToolCall("get_order_by_number", {"order_number": document_number or ""})]
    if "ultimo pedido" in normalized or ("pedido" in normalized and document_number):
        return [ToolCall("get_order_by_number", {"order_number": document_number or ""})]
    if "duplicad" in normalized:
        return [ToolCall("get_duplicate_documents", {})]
    if "baja confianza" in normalized or "error ocr" in normalized or "confianza ocr" in normalized:
        return [ToolCall("get_ocr_review_documents", {})]
    if "entidad" in normalized and "referencia" in normalized:
        value = _extract_reference(question)
        return [ToolCall("search_entities", {"entity_type": "reference", "value": value or question})]
    if ("mide" in normalized or "medida" in normalized or "superficie" in normalized) and (
        room_name := _extract_room_name(normalized)
    ):
        return [ToolCall("search_plan_room_measurements", {"room_name": room_name})]
    if "plano" in normalized or "medida" in normalized or "salon" in normalized or "escala" in normalized:
        return [ToolCall("hybrid_search", {"query": question, "filters": {"document_type": "plano", "limit": 8}})]

    # General question: try hybrid_search with re-ranking filters when the
    # user hints at supplier / client / amount.
    search_filters = {"limit": 8}
    _maybe_apply_relevance_filter(search_filters, normalized, question)
    return [ToolCall("hybrid_search", {"query": question, "filters": search_filters})]


# ---------------------------------------------------------------------------
# Question-classification helpers (aggregation + re-ranking)
# ---------------------------------------------------------------------------


# Words that signal "the user wants a SQL-style aggregation, not a
# text match". Order does not matter; the helper uses ``in``.
_AGGREGATION_HINTS = (
    "cuanto", "cuanta", "total", "suma", "importe total", "gastado",
    "facturado", "cobrado", "numero de", "cuantos", "cuantas",
    "promedio", "media", "top", "mayor", "menor",
)


def _is_aggregation_question(normalized: str) -> bool:
    return any(h in normalized for h in _AGGREGATION_HINTS)


def _classify_aggregation(normalized: str) -> tuple[str, str]:
    """Return (entity, kind) for an aggregation question.

    - entity: 'budget' | 'order' | 'invoice'
    - kind:   'count' | 'total' | 'top' | 'by_supplier'
    """
    if "factur" in normalized:
        entity = "invoice"
    elif "pedido" in normalized:
        entity = "order"
    else:
        entity = "budget"

    if any(w in normalized for w in ("cuanto", "cuanta", "total", "suma", "importe", "gastado", "facturado")):
        kind = "total"
    elif any(w in normalized for w in ("top", "mayor", "mas alto", "mas grande")):
        kind = "top"
    elif "por proveedor" in normalized or "por cada proveedor" in normalized:
        kind = "by_supplier"
    else:
        kind = "count"
    return entity, kind


def _maybe_apply_relevance_filter(filters: dict, normalized: str, original_question: str) -> None:
    """Add `document_type`, `supplier_ilike`, `client_ilike`, or amount
    bounds to the hybrid_search filters when the user hints at them in the
    question. The search service is responsible for actually applying them
    (see search_service.py)."""
    if "plano" in normalized:
        filters["document_type"] = "plano"
    elif "pedido" in normalized:
        filters["document_type"] = "pedido"
    elif "presupuest" in normalized:
        filters["document_type"] = "presupuesto"
    elif "factura" in normalized:
        filters["document_type"] = "factura"

    money = _money_filters("", original_question)
    if money.get("supplier"):
        filters["supplier_ilike"] = f"%{money['supplier']}%"
    if money.get("client"):
        filters["client_ilike"] = f"%{money['client']}%"
    if money.get("amount_min") is not None:
        filters["amount_min"] = money["amount_min"]
    if money.get("amount_max") is not None:
        filters["amount_max"] = money["amount_max"]


# ---------------------------------------------------------------------------
# Question-text helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase + strip accents for keyword matching. The original
    casing/accented text is preserved in the LLM prompt; this is
    only used for the cheap, in-Python keyword checks."""
    normalized = unicodedata.normalize("NFKD", text.lower())
    return normalized.encode("ascii", "ignore").decode("ascii")


def _extract_document_number(text: str) -> str | None:
    """Pull a presupuesto / pedido number from a free-form question.

    Tries three patterns in order of specificity:
    1. ``2024/1234`` style (Spanish budget format).
    2. ``prefix-NNN`` style (alphanumeric budget/order ids).
    3. A pure numeric id of 5-7 digits (legacy short codes).
    """
    match = re.search(r"\b\d{4}/\d+\b", text)
    if match:
        return match.group(0)
    match = re.search(r"\b[A-Za-z]{0,8}\d{2,}[-/]\d+\b", text)
    if match:
        return match.group(0)
    match = re.search(r"\b\d{5,7}\b", text)
    return match.group(0) if match else None


def _extract_reference(text: str) -> str | None:
    """Pick up an alphanumeric reference token like ``MAT-001`` or
    ``REF12345``. Returns the first match or None."""
    match = re.search(r"\b[A-Za-z]{2,}\d{2,}[A-Za-z0-9-]*\b", text)
    return match.group(0) if match else None


_FILENAME_HINT = re.compile(
    r"\b[\w./-]+\.(?:pdf|msg|docx|doc|xlsx|xls|xlsm|csv|tsv|png|jpe?g|tiff?|bmp|webp|eml|txt)\b",
    flags=re.IGNORECASE,
)


def _extract_filenames(text: str) -> list[str]:
    """Find filename-like tokens in the user's question. Stops common
    false positives like URLs by requiring a document extension at
    the end."""
    return _FILENAME_HINT.findall(text or "")


def _extract_room_name(normalized_question: str) -> str | None:
    """Pick up the name of a room the user is asking about.

    The list is intentionally short: it covers the most common
    Spanish room names. When the question mentions a room that is
    not in the list, we fall back to a regex that captures the noun
    after "mide" / "medida" / "superficie".
    """
    known_rooms = [
        "salon",
        "cocina",
        "dormitorio",
        "habitacion",
        "bano",
        "banio",
        "aseo",
        "pasillo",
        "comedor",
        "terraza",
        "garaje",
        "recibidor",
    ]
    for room in known_rooms:
        if room in normalized_question:
            return "bano" if room == "banio" else room
    match = re.search(r"(?:mide|medida|superficie)\s+(?:del|de la|de el|el|la)?\s*([a-z0-9 ]{3,30})", normalized_question)
    if match:
        return match.group(1).strip()
    return None
