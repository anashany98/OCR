"""Tests for the multi-language tool selector (AI-007).

The previous selector in ``app.ai.tools`` hardcoded Spanish
keywords (``presupuest``, ``pedido``, ``factura`` …) which meant
that questions in English, French, German, Italian or Portuguese
always fell through to the generic ``hybrid_search`` fallback
instead of being routed to the dedicated structured tools
(``aggregate_business``, ``get_budget_by_number``,
``search_plan_room_measurements`` …).

These tests pin down the behaviour of the new lexicon-aware
selector across the working languages of the platform. Each test
is parameterised so adding a new language for an existing intent
is a one-line change in the parametrize block.

The tests only exercise :func:`app.ai.tools.select_tools_for_question`
and the small helpers it delegates to, so they need no DB, no
Redis, no FastAPI test client and no GPU.
"""
from __future__ import annotations

import pytest

from app.ai import tools
from app.ai.tools import (
    ToolCall,
    select_tools_for_question,
)


def test_delivery_note_amount_is_not_misrouted_to_global_aggregation() -> None:
    selected = select_tools_for_question("Cual es el importe del albarán?")

    assert [tool.name for tool in selected] == ["hybrid_search"]
    assert selected[0].arguments["filters"]["document_type"] == "albaran"
    assert selected[0].arguments["query"] == "albaran"


def test_low_ocr_question_keeps_document_specific_retrieval() -> None:
    selected = select_tools_for_question(
        "Que informacion fiable se puede extraer del PDF de incidencia de sillas si la confianza OCR es baja?"
    )

    assert [tool.name for tool in selected] == [
        "find_document_by_filename",
        "get_document_full_details",
        "get_related_documents",
        "get_ocr_review_documents",
    ]
    assert selected[0].arguments["query"] == "incidencia sillas"


# ---------------------------------------------------------------------------
# Aggregation intent (SQL over structured tables) — 6 languages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,expected_entity,expected_kind",
    [
        # Spanish (existing)
        ("cuanto nos hemos gastado en MELIA", "budget", "total"),
        ("cuantos pedidos hay en mayo", "order", "total"),
        ("total facturado a MELIA", "invoice", "total"),
        ("top 5 presupuestos", "budget", "top"),
        # English
        ("how much did we spend on MELIA", "budget", "total"),
        ("how many orders are there in May", "order", "count"),
        ("total invoiced to MELIA", "invoice", "total"),
        ("top 5 budgets", "budget", "top"),
        # French
        ("combien avons-nous depense pour MELIA", "budget", "total"),
        ("combien de commandes en mai", "order", "total"),
        ("total facture a MELIA", "invoice", "total"),
        # German
        ("wieviel haben wir fuer MELIA ausgegeben", "budget", "total"),
        ("wieviele bestellungen im Mai", "order", "total"),
        ("summe rechnungen an MELIA", "invoice", "total"),
        # Italian
        ("quanto abbiamo speso per MELIA", "budget", "total"),
        ("quanti ordini a maggio", "order", "count"),
        ("totale fatture a MELIA", "invoice", "total"),
        # Portuguese
        ("quanto gastamos com a MELIA", "budget", "total"),
        ("quantos pedidos em maio", "order", "total"),
        ("total faturado para MELIA", "invoice", "total"),
    ],
)
def test_select_tools_aggregation_routes_by_language(
    question: str, expected_entity: str, expected_kind: str
) -> None:
    tools_selected = select_tools_for_question(question)
    # Aggregation questions must always call ``aggregate_business``
    # first so the SQL is the primary source of context.
    assert tools_selected[0].name == "aggregate_business"
    assert tools_selected[0].arguments["entity"] == expected_entity
    assert tools_selected[0].arguments["kind"] == expected_kind
    # And must include a hybrid_search follow-up so the LLM can
    # cite the matching documents.
    assert any(t.name == "hybrid_search" for t in tools_selected)


# ---------------------------------------------------------------------------
# Document lookup by number — multi-language keyword
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,expected_primary_tool",
    [
        # Spanish
        ("dame el presupuesto 2024/154", "get_budget_by_number"),
        ("dame el pedido 2024/155", "get_order_by_number"),
        # English
        ("show me budget 2024/154", "get_budget_by_number"),
        ("show me purchase order 2024/155", "get_order_by_number"),
        # French
        ("devis 2024/154", "get_budget_by_number"),
        ("commande 2024/155", "get_order_by_number"),
        # German
        ("angebot 2024/154", "get_budget_by_number"),
        ("bestellung 2024/155", "get_order_by_number"),
        # Italian
        ("preventivo 2024/154", "get_budget_by_number"),
        ("ordine 2024/155", "get_order_by_number"),
        # Portuguese
        ("orcamento 2024/154", "get_budget_by_number"),
        ("pedido 2024/155", "get_order_by_number"),
    ],
)
def test_select_tools_lookup_by_number_routes_by_language(
    question: str, expected_primary_tool: str
) -> None:
    tools_selected = select_tools_for_question(question)
    assert tools_selected[0].name == expected_primary_tool


# ---------------------------------------------------------------------------
# Plans / blueprints / floor plans — multi-language synonym
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        # Spanish
        "tienes el plano de la planta baja",
        "dame el plano del salon",
        "croquis del primer piso",
        # English
        "do you have the floor plan for the ground floor",
        "show me the blueprint",
        "drawings of the second floor",
        # French
        "as-tu le plan du rez-de-chaussee",
        # German
        "hast du den grundriss vom erdgeschoss",
        # Italian
        "hai la pianta del piano terra",
        "disegno del secondo piano",
        # Portuguese
        "voce tem a planta do terreo",
    ],
)
def test_select_tools_plan_question_routes_to_plan_filter(question: str) -> None:
    tools_selected = select_tools_for_question(question)
    # Plan question must not fall through to a generic
    # ``hybrid_search`` without the ``document_type=plano`` filter.
    assert tools_selected[0].name == "hybrid_search"
    assert tools_selected[0].arguments["filters"]["document_type"] == "plano"


# ---------------------------------------------------------------------------
# Room measurement — multi-language room name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,expected_room",
    [
        # Spanish
        ("mide el salon", "salon"),
        ("superficie del bano", "bano"),
        ("medidas de la cocina", "cocina"),
        ("medidas del dormitorio", "dormitorio"),
        ("area del pasillo", "pasillo"),
        # English
        ("how big is the kitchen", "kitchen"),
        ("size of the bedroom", "bedroom"),
        ("square meters of the bathroom", "bathroom"),
        ("area of the living room", "living_room"),
        # Italian
        ("dimensione del soggiorno", "soggiorno"),
        ("dimensione della camera", "camera"),
        # Portuguese
        ("tamanho do quarto", "quarto"),
        ("area da cozinha", "cozinha"),
        # French
        ("taille du salon", "salon"),
        ("surface de la chambre", "chambre"),
    ],
)
def test_select_tools_room_measurement_recognises_languages(
    question: str, expected_room: str
) -> None:
    tools_selected = select_tools_for_question(question)
    assert tools_selected[0].name == "search_plan_room_measurements"
    assert tools_selected[0].arguments["room_name"] == expected_room


# ---------------------------------------------------------------------------
# Accepted budgets without order — multi-language
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        # Spanish
        "dame los presupuestos aceptados sin pedido",
        "presupuestos sin orden de compra",
        # English
        "show me accepted budgets without purchase order",
        "approved budgets missing PO",
        # French
        "budgets acceptes sans commande",
        # Italian
        "preventivi accettati senza ordine",
    ],
)
def test_select_tools_accepted_without_order_recognises_languages(question: str) -> None:
    tools_selected = select_tools_for_question(question)
    assert tools_selected[0].name == "get_accepted_budgets_without_order"


# ---------------------------------------------------------------------------
# Duplicates — multi-language
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "documentos duplicados",
        "show me duplicates",
        "doublons",
        "doppelte dokumente",
        "documenti duplicati",
    ],
)
def test_select_tools_duplicates_recognises_languages(question: str) -> None:
    tools_selected = select_tools_for_question(question)
    assert tools_selected[0].name == "get_duplicate_documents"


# ---------------------------------------------------------------------------
# Low OCR confidence — multi-language
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "documentos con baja confianza OCR",
        "documentos con error ocr",
        "low confidence OCR documents",
        "ocr errors",
        "review ocr",
        "faible confiance",
        "niedrige qualitaet",
        "bassa qualita",
    ],
)
def test_select_tools_low_ocr_recognises_languages(question: str) -> None:
    tools_selected = select_tools_for_question(question)
    assert tools_selected[0].name == "get_ocr_review_documents"


# ---------------------------------------------------------------------------
# Word-boundary regression: "pedido" must not match inside "expedido"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "expedido en mayo",  # not a budget/order lookup
        "ha sido impedido por el proveedor",  # not an order lookup
        "expediente del cliente",  # not an invoice lookup
    ],
)
def test_select_tools_does_not_match_substring_of_other_words(question: str) -> None:
    """The old ``in`` substring check would route
    ``expedido en mayo`` to ``get_order_by_number`` because the
    word ``pedido`` appears inside ``expedido``. The new
    whole-word stem matcher must leave that to a generic
    ``hybrid_search`` so we do not silently mis-classify.
    """
    tools_selected = select_tools_for_question(question)
    names = [t.name for t in tools_selected]
    assert "get_order_by_number" not in names
    assert "get_budget_by_number" not in names
    assert "get_duplicate_documents" not in names
    # Final fallback is a generic hybrid_search.
    assert "hybrid_search" in names


# ---------------------------------------------------------------------------
# Fallback path: ambiguous question falls through to hybrid_search with
# inferred filters when the lexicon does not match anything.
# ---------------------------------------------------------------------------


def test_select_tools_falls_back_to_hybrid_search() -> None:
    tools_selected = select_tools_for_question("cuentame algo del proyecto")
    assert tools_selected[0].name == "hybrid_search"
    # No document_type filter inferred from this question.
    assert "document_type" not in tools_selected[0].arguments.get("filters", {})


# ---------------------------------------------------------------------------
# _contains_word helper sanity check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "haystack,needle,expected",
    [
        ("pedido 2024/154", "pedido", True),
        ("expedido en mayo", "pedido", False),
        ("how much did we invoice MELIA", "invoice", True),
        ("the invoices are wrong", "invoice", True),
        ("the invoices are wrong", "invoices", True),
        ("this is unrelated", "invoice", False),
        ("total facturado", "facturad", True),  # participle stem
        ("total facturado", "factura", True),  # lemma
        ("this is not about money", "factura", False),
    ],
)
def test_contains_word_helper(haystack: str, needle: str, expected: bool) -> None:
    assert tools._contains_word(haystack, needle) is expected
