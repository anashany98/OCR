"""Unit tests for the Graph RAG routing in ``app.ai.intent_router``.

These tests pin the contract added by the
``PLAN_ARQUITECTURA_PGVECTOR_GRAPH_RAG.md`` §3.3 router extension:

* questions that imply walking the entity/relation catalogue
  resolve to ``INTENT_RELATED_DOCUMENTS`` with
  ``retrieval_strategy == "graph"``;
* the legacy "documentos relacionados" pattern still resolves to
  the same intent (no regression in the existing surface);
* generic business intents keep the default ``hybrid`` strategy.
"""
from __future__ import annotations

import pytest

from app.ai.intent_router import (
    INTENT_RELATED_DOCUMENTS,
    RETRIEVAL_STRATEGY_GRAPH,
    RETRIEVAL_STRATEGY_HYBRID,
    classify_intent,
)


@pytest.mark.parametrize(
    "question",
    [
        "que documentos estan relacionados con el presupuesto 2026/143",
        "documentos vinculados al pedido P-77",
        "que relaciones tiene el documento X",
        "documentos asociados con el albaran A-12",
        "relacionados con el presupuesto 2026/143",
    ],
)
def test_graph_routed_questions_set_retrieval_strategy_to_graph(question):
    cls = classify_intent(question)
    assert cls.intent == INTENT_RELATED_DOCUMENTS
    assert cls.retrieval_strategy == RETRIEVAL_STRATEGY_GRAPH


def test_factura_keyword_keeps_invoice_origin_intent():
    """The legacy invoice-origin pattern wins over the graph-routed
    variant when the question names a specific document type. This is
    intentional: the structured invoice tool has priority over the
    generic graph lookup because it can resolve the answer with a
    single SQL join. The router surface does not regress.
    """
    cls = classify_intent("que documentos estan conectados con la factura F-2026-044")
    assert cls.intent != INTENT_RELATED_DOCUMENTS
    assert cls.retrieval_strategy == RETRIEVAL_STRATEGY_HYBRID


def test_legacy_related_pattern_still_routes_to_related_documents():
    """The pre-existing pattern bank is preserved; it now also gets
    the ``graph`` strategy because the intent is in the
    ``_GRAPH_ROUTED_INTENTS`` set."""
    cls = classify_intent("documentos relacionados con el presupuesto 2026/143")
    assert cls.intent == INTENT_RELATED_DOCUMENTS
    assert cls.retrieval_strategy == RETRIEVAL_STRATEGY_GRAPH


def test_generic_intent_keeps_hybrid_strategy():
    cls = classify_intent("por cuanto esta presupuestado el presupuesto 2026/143")
    assert cls.retrieval_strategy == RETRIEVAL_STRATEGY_HYBRID


def test_empty_question_returns_hybrid_strategy():
    cls = classify_intent("")
    assert cls.intent == "generic_document_question"
    assert cls.retrieval_strategy == RETRIEVAL_STRATEGY_HYBRID
