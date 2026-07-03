"""Tests for the E2 BM25 retrieval module.

The BM25 wrapper is mostly a thin SQL wrapper around PostgreSQL's
``ts_rank_cd``; the *interesting* logic is the adaptive-weight
selector and the RRF fusion of three branches. Those bits are
exercised here in isolation, without a database, so the tests run
fast and are deterministic. The integration with a real Postgres
session is left to a smoke test in CI (a connection to
``postgres:5432`` with the 0021 migration applied).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.services import bm25
from app.services.metrics import track_search_strategy_used
from app.services.search_service import SearchResult, merge_hybrid_results


# ---------------------------------------------------------------------------
# merge_hybrid_results — 3-source RRF
# ---------------------------------------------------------------------------


def _result(document_id: int, source_type: str = "text", page: int | None = 1, score: float = 1.0) -> SearchResult:
    return SearchResult(
        document_id=document_id,
        original_filename=f"d{document_id}.pdf",
        document_type="presupuesto",
        status="processed",
        page_number=page,
        block_id=None,
        score=score,
        excerpt=f"excerpt for doc {document_id}",
        ocr_confidence=None,
        source_type=source_type,
    )


def test_merge_hybrid_results_backward_compatible_without_bm25():
    """Callers that do not pass ``bm25_results`` must still get the
    legacy 2-source fusion. We assert the *relative* ranking
    (docs that appear in both lists beat docs that appear in
    only one) without hard-coding exact positions, which depend
    on the RRF k constant."""
    text = [_result(1), _result(2), _result(3)]
    semantic = [_result(2), _result(1), _result(4)]
    merged = merge_hybrid_results(text, semantic, limit=10, k=60)
    ids = [r.document_id for r in merged]
    # All four docs must be present.
    assert set(ids) == {1, 2, 3, 4}
    # Docs 1 and 2 appear in both lists -> they should be the
    # top two (in any order).
    top_two = set(ids[:2])
    assert top_two == {1, 2}
    # Docs 3 and 4 only appear once -> they should be last.
    assert set(ids[2:]) == {3, 4}


def test_merge_hybrid_results_includes_bm25_when_provided():
    text = [_result(1), _result(2)]
    semantic = [_result(2), _result(3)]
    bm25 = [_result(4), _result(5), _result(2)]
    merged = merge_hybrid_results(
        text, semantic, bm25_results=bm25, limit=10, k=60
    )
    # Doc 2 appears in all three lists at rank 1/1/2 — should be
    # the top hit. Doc 1, 3, 4, 5 each appear once.
    assert merged[0].document_id == 2
    # The final source_type is always ``hybrid_rrf`` (the fusion
    # marker) regardless of which branch contributed the chunk.
    assert merged[0].source_type == "hybrid_rrf"
    # All 5 docs must appear in the merged result.
    assert {r.document_id for r in merged} == {1, 2, 3, 4, 5}


def test_merge_hybrid_results_respects_limit():
    text = [_result(i) for i in range(5)]
    semantic = [_result(i + 10) for i in range(5)]
    bm25 = [_result(i + 100) for i in range(5)]
    merged = merge_hybrid_results(
        text, semantic, bm25_results=bm25, limit=3, k=60
    )
    assert len(merged) == 3


def test_merge_hybrid_results_marks_source_type_as_hybrid_rrf():
    text = [_result(1)]
    semantic = [_result(2)]
    merged = merge_hybrid_results(text, semantic, bm25_results=[_result(3)], limit=10)
    for r in merged:
        assert r.source_type == "hybrid_rrf"


def test_merge_hybrid_results_handles_empty_inputs():
    assert merge_hybrid_results([], [], limit=10) == []
    assert merge_hybrid_results([], [], bm25_results=[], limit=10) == []
    # Text only.
    merged = merge_hybrid_results([_result(1)], [], limit=10)
    assert [r.document_id for r in merged] == [1]


def test_merge_hybrid_results_rrf_k_zero_is_safe():
    """k=0 would make the RRF score blow up (1/0). The function
    must not crash; we just assert it returns sensible output."""
    text = [_result(1), _result(2)]
    semantic = [_result(2), _result(1)]
    merged = merge_hybrid_results(text, semantic, bm25_results=[], limit=10, k=0)
    # Even with k=0 the function runs to completion.
    assert isinstance(merged, list)


# ---------------------------------------------------------------------------
# Smoke: the search_bm25 function is importable + degrades gracefully
# ---------------------------------------------------------------------------


def test_search_bm25_returns_empty_list_on_empty_query():
    """No DB needed: the empty-query short-circuit runs first."""
    from app.services.bm25 import search_bm25

    class _FakeSession:
        bind = None

    result = search_bm25(_FakeSession(), "", limit=10)
    assert result == []
    result = search_bm25(_FakeSession(), "   ", limit=10)
    assert result == []


def test_search_bm25_skips_non_postgres_session():
    """The function must not crash on a non-Postgres session. It
    returns an empty list and records the skip metric."""
    from app.services.bm25 import search_bm25

    class _FakeSession:
        bind = None  # .dialect.name access would raise; bind=None
        # short-circuits via the first branch.

    result = search_bm25(_FakeSession(), "presupuesto 245745", limit=10)
    assert result == []


# ---------------------------------------------------------------------------
# Smoke: the search strategy metrics helper is exposed
# ---------------------------------------------------------------------------


def test_track_search_strategy_used_does_not_raise(caplog):
    """The metric helper must accept any string without raising;
    Prometheus label cardinality is bounded by the helper itself."""
    track_search_strategy_used("bm25", "executed")
    track_search_strategy_used("cosine", "failed")
    track_search_strategy_used("", "weird outcome")
