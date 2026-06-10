"""Tests for the R1 query transformer.

The transformer has two halves:

* **Pure** logic (auto-method selection, response parsing,
  fallback to the original query when the LLM is missing).
* **Async** LLM calls that we cannot exercise in unit tests
  without a real or fake LLM server.

The pure logic is tested here in full. The LLM path is exercised
by monkeypatching the ``LocalOpenAICompatibleClient`` so the
tests stay deterministic and fast; the patched path is the
*only* code path the production transformer calls in the LLM
branch.

The goal is to lock the contract: a transformer call always
returns a :class:`QueryTransformation` whose
``transformed_queries`` list starts with the original query; a
failed LLM call yields an ``outcome="fallback"``; a disabled
transformer yields ``outcome="disabled"``.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.services import query_transformer
from app.services.metrics import track_query_transform
from app.services.query_transformer import (
    QueryTransformation,
    auto_select_method,
    transform_query,
    _parse_hyde_response,
    _parse_multi_query_response,
)


# ---------------------------------------------------------------------------
# auto_select_method
# ---------------------------------------------------------------------------


def test_auto_select_method_picks_hyde_for_natural_language():
    """A long question with at least one long word -> HyDE."""
    method = auto_select_method("Cuál es el último pedido del proveedor García este año")
    assert method == "hyde"


def test_auto_select_method_picks_multi_query_for_terse():
    """A short or code-like query -> multi_query (multiple
    reformulations catch more vocabulary than a single
    hypothetical)."""
    assert auto_select_method("presupuesto 245745") == "multi_query"
    assert auto_select_method("NIF B123") == "multi_query"
    assert auto_select_method("") == "multi_query"


def test_auto_select_method_handles_empty_input():
    assert auto_select_method("") == "multi_query"


def test_auto_select_method_treats_punctuation_neutrally():
    """HyDE / multi-query decision is on word count + long-word
    count; punctuation does not flip the choice."""
    method = auto_select_method("cuál es el último pedido del proveedor García")
    assert method == "hyde"


# ---------------------------------------------------------------------------
# _parse_multi_query_response
# ---------------------------------------------------------------------------


def test_parse_multi_query_response_drops_empty_lines_and_dedupes():
    text = (
        "Último pedido del proveedor García\n"
        "\n"
        "Pedido más reciente de García\n"
        "último pedido del proveedor garcía\n"  # duplicate, case-insensitive
        "Pedido reciente de Garcia 2025"
    )
    out = _parse_multi_query_response(text, max_queries=10)
    assert out == [
        "Último pedido del proveedor García",
        "Pedido más reciente de García",
        "Pedido reciente de Garcia 2025",
    ]


def test_parse_multi_query_response_strips_list_markers():
    text = (
        "1. Primera reformulacion\n"
        "2) Segunda reformulacion\n"
        "- Tercera reformulacion\n"
        "* Cuarta reformulacion\n"
        "• Quinta reformulacion"
    )
    out = _parse_multi_query_response(text, max_queries=10)
    assert out == [
        "Primera reformulacion",
        "Segunda reformulacion",
        "Tercera reformulacion",
        "Cuarta reformulacion",
        "Quinta reformulacion",
    ]


def test_parse_multi_query_response_strips_quotes():
    text = '"Reformulacion A"\n\'Reformulacion B\''
    out = _parse_multi_query_response(text, max_queries=10)
    assert out == ["Reformulacion A", "Reformulacion B"]


def test_parse_multi_query_response_respects_max_queries():
    text = "uno\ndos\ntres\ncuatro\ncinco"
    out = _parse_multi_query_response(text, max_queries=2)
    assert out == ["uno", "dos"]


def test_parse_multi_query_response_handles_empty_text():
    assert _parse_multi_query_response("", max_queries=10) == []
    assert _parse_multi_query_response("   \n  \n", max_queries=10) == []


# ---------------------------------------------------------------------------
# _parse_hyde_response
# ---------------------------------------------------------------------------


def test_parse_hyde_response_strips_common_preambles():
    assert _parse_hyde_response("Aquí tienes el párrafo: este es el contenido") == "este es el contenido"
    assert _parse_hyde_response("Certainly! this is the content") == "this is the content"
    assert _parse_hyde_response("Sure! paragraph body") == "paragraph body"
    assert _parse_hyde_response("Here is a passage: body") == "body"
    assert _parse_hyde_response("Here's the text: body") == "body"


def test_parse_hyde_response_passes_through_clean_text():
    body = "La factura 245745 fue emitida el 12 de marzo por 12.450 EUR."
    assert _parse_hyde_response(body) == body


def test_parse_hyde_response_handles_empty():
    assert _parse_hyde_response("") == ""
    assert _parse_hyde_response("   ") == ""


# ---------------------------------------------------------------------------
# transform_query — sync wrapper
# ---------------------------------------------------------------------------


def test_transform_query_disabled_returns_original_only(monkeypatch):
    """``method='off'`` returns the original query with the
    ``disabled`` outcome, no LLM call attempted."""
    from app.services.query_transformer import transform_query
    import asyncio

    called = {"count": 0}

    async def fake_hyde(query):
        called["count"] += 1
        return "should not be called"

    async def fake_multi(query, n):
        called["count"] += 1
        return ["should not be called"]

    monkeypatch.setattr(query_transformer, "_call_llm_for_hyde", fake_hyde)
    monkeypatch.setattr(query_transformer, "_call_llm_for_multi_query", fake_multi)

    result = transform_query("presupuesto 245745", method="off")
    assert result.method == "off"
    assert result.outcome == "disabled"
    assert result.transformed_queries == ["presupuesto 245745"]
    assert result.original_query == "presupuesto 245745"
    assert called["count"] == 0


def test_transform_query_hyde_success(monkeypatch):
    """A successful HyDE call returns the original query + the
    hypothetical."""
    import asyncio

    async def fake_hyde(query):
        return "Este es un parrafo hipotetico del documento."

    monkeypatch.setattr(query_transformer, "_call_llm_for_hyde", fake_hyde)

    result = transform_query("Cuál es el último pedido del proveedor García", method="hyde")
    assert result.method == "hyde"
    assert result.outcome == "success"
    assert result.transformed_queries[0] == "Cuál es el último pedido del proveedor García"
    assert "parrafo hipotetico" in result.transformed_queries[1]


def test_transform_query_hyde_fallback_when_llm_returns_none(monkeypatch):
    """A failed HyDE call (LLM returns None) falls back to the
    original query only and records the fallback outcome."""
    async def fake_hyde(query):
        return None

    monkeypatch.setattr(query_transformer, "_call_llm_for_hyde", fake_hyde)
    monkeypatch.setattr(query_transformer.settings, "ai_base_url", "http://fake", raising=False)
    monkeypatch.setattr(query_transformer.settings, "ai_model", "fake-model", raising=False)

    result = transform_query("Cuál es el último pedido del proveedor García", method="hyde")
    assert result.method == "hyde"
    assert result.outcome == "fallback"
    assert result.transformed_queries == ["Cuál es el último pedido del proveedor García"]


def test_transform_query_multi_query_success(monkeypatch):
    """A successful multi-query call returns the original query
    + the LLM's reformulations."""
    async def fake_multi(query, n):
        return [
            "Último pedido de García",
            "Pedido más reciente del proveedor García",
            "Pedido reciente García 2025",
        ]

    monkeypatch.setattr(query_transformer, "_call_llm_for_multi_query", fake_multi)
    monkeypatch.setattr(query_transformer.settings, "ai_base_url", "http://fake", raising=False)
    monkeypatch.setattr(query_transformer.settings, "ai_model", "fake-model", raising=False)

    result = transform_query("presupuesto Garcia 245745", method="multi_query", max_queries=3)
    assert result.method == "multi_query"
    assert result.outcome == "success"
    assert result.transformed_queries[0] == "presupuesto Garcia 245745"
    assert len(result.transformed_queries) == 4  # original + 3 reformulations


def test_transform_query_multi_query_fallback_when_llm_returns_empty(monkeypatch):
    async def fake_multi(query, n):
        return []

    monkeypatch.setattr(query_transformer, "_call_llm_for_multi_query", fake_multi)
    monkeypatch.setattr(query_transformer.settings, "ai_base_url", "http://fake", raising=False)
    monkeypatch.setattr(query_transformer.settings, "ai_model", "fake-model", raising=False)

    result = transform_query("presupuesto Garcia 245745", method="multi_query")
    assert result.outcome == "fallback"
    assert result.transformed_queries == ["presupuesto Garcia 245745"]


def test_transform_query_auto_picks_hyde_for_natural_language(monkeypatch):
    async def fake_hyde(query):
        return "parrafo hipotetico"

    monkeypatch.setattr(query_transformer, "_call_llm_for_hyde", fake_hyde)
    monkeypatch.setattr(query_transformer.settings, "ai_base_url", "http://fake", raising=False)
    monkeypatch.setattr(query_transformer.settings, "ai_model", "fake-model", raising=False)

    result = transform_query(
        "Cuál es el último pedido del proveedor García este año",
        method="auto",
    )
    assert result.method == "hyde"


def test_transform_query_auto_picks_multi_query_for_terse(monkeypatch):
    async def fake_multi(query, n):
        return ["reform 1", "reform 2"]

    monkeypatch.setattr(query_transformer, "_call_llm_for_multi_query", fake_multi)
    monkeypatch.setattr(query_transformer.settings, "ai_base_url", "http://fake", raising=False)
    monkeypatch.setattr(query_transformer.settings, "ai_model", "fake-model", raising=False)

    result = transform_query("presupuesto Garcia 245745", method="auto")
    assert result.method == "multi_query"


def test_transform_query_handles_empty_input():
    result = transform_query("", method="hyde")
    # An empty query is treated as "disabled" by the upstream
    # guard: we never even consult the method argument. The
    # dataclass invariant says ``transformed_queries`` is
    # non-empty (it always contains the original query, even if
    # that is an empty string) so callers can iterate without
    # nil-checking.
    assert result.method == "off"
    assert result.outcome == "disabled"
    assert result.original_query == ""
    assert result.transformed_queries == [""]


def test_transform_query_unknown_method_falls_back_to_off(monkeypatch):
    """A typo in the strategy name is treated as 'off' (do not
    call the LLM, return the original query)."""
    result = transform_query("any query", method="bogus")
    assert result.method == "off"
    assert result.outcome == "disabled"


def test_transform_query_disabled_via_setting(monkeypatch):
    """When ``search_use_query_transformer`` is False, the
    transformer is off regardless of the requested method."""
    monkeypatch.setattr(query_transformer.settings, "search_use_query_transformer", False)
    result = transform_query("presupuesto Garcia 245745", method="hyde")
    assert result.method == "hyde"
    assert result.outcome == "disabled"
    assert result.transformed_queries == ["presupuesto Garcia 245745"]


# ---------------------------------------------------------------------------
# Smoke: the metric helper is exposed
# ---------------------------------------------------------------------------


def test_track_query_transform_does_not_raise(caplog):
    """The metric helper must accept any string without raising;
    Prometheus label cardinality is bounded by the helper itself."""
    track_query_transform("hyde", "success", latency_ms=120)
    track_query_transform("multi_query", "fallback", latency_ms=0)
    track_query_transform("", "weird outcome")
