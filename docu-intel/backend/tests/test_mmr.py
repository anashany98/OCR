"""Tests for the E5 Maximal Marginal Relevance reranker.

The MMR loop is pure: it consumes a list of SearchResult, picks
``top_k`` by the classic relevance + novelty formula, and
returns a :class:`MMRResult`. The similarity function is
pluggable; the default n-gram Jaccard is exercised in full. The
integration with the real search is left to a smoke test in CI
(both run against the same in-memory pool).

The tests assert:
* the top-k is preserved in count;
* diversity is at least as high as plain top-k-by-relevance
  (we measure it as the average n-gram Jaccard between hits);
* the fail-safe branches (empty input, top_k=0, lambda=1,
  pool smaller than top_k) all return the expected shape;
* the dataclass is correctly populated.
"""
from __future__ import annotations

from typing import Iterable

import pytest

from app.services import mmr
from app.services.mmr import (
    MMRResult,
    _average_pairwise_similarity,
    _excerpt_similarity,
    jaccard_ngram_similarity,
    mmr_rerank,
)
from app.services.search_service import SearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(
    document_id: int,
    excerpt: str,
    *,
    score: float = 1.0,
    source_type: str = "bm25",
) -> SearchResult:
    return SearchResult(
        document_id=document_id,
        original_filename=f"d{document_id}.pdf",
        document_type="presupuesto",
        status="processed",
        page_number=1,
        block_id=None,
        score=score,
        excerpt=excerpt,
        ocr_confidence=None,
        source_type=source_type,
        source_path=None,
    )


# ---------------------------------------------------------------------------
# jaccard_ngram_similarity
# ---------------------------------------------------------------------------


def test_jaccard_ngram_similarity_identical_strings():
    text = "El presupuesto 245745 por importe de 12.450 EUR"
    assert jaccard_ngram_similarity(text, text) == pytest.approx(1.0)


def test_jaccard_ngram_similarity_disjoint_strings():
    a = "abcdef"
    b = "ghijkl"
    # 3-grams of "abcdef": abc, bcd, cde, def. Of "ghijkl": ghi, hij, ijk, jkl.
    # Intersection = empty. Jaccard = 0.
    assert jaccard_ngram_similarity(a, b) == 0.0


def test_jaccard_ngram_similarity_partial_overlap():
    a = "Factura 245745 total EUR"
    b = "Factura 245746 total EUR"  # 1 char diff
    sim = jaccard_ngram_similarity(a, b)
    # High but not 1.0.
    assert 0.5 < sim < 1.0


def test_jaccard_ngram_similarity_is_case_insensitive():
    assert jaccard_ngram_similarity("Factura", "factura") == pytest.approx(1.0)


def test_jaccard_ngram_similarity_handles_empty_inputs():
    assert jaccard_ngram_similarity("", "") == 0.0
    assert jaccard_ngram_similarity("", "abc") == 0.0
    assert jaccard_ngram_similarity("abc", "") == 0.0


def test_jaccard_ngram_similarity_handles_short_inputs():
    """Strings shorter than ``n`` collapse to a single n-gram
    (the whole string). Two short distinct strings are still
    considered different."""
    assert jaccard_ngram_similarity("ab", "ab") == pytest.approx(1.0)
    assert jaccard_ngram_similarity("ab", "cd") == 0.0


# ---------------------------------------------------------------------------
# _excerpt_similarity (uses jaccard_ngram_similarity internally)
# ---------------------------------------------------------------------------


def test_excerpt_similarity_handles_missing_excerpt():
    a = _result(1, "some text")
    b = _result(2, "")  # empty excerpt
    assert _excerpt_similarity(a, b) == 0.0
    assert _excerpt_similarity(b, a) == 0.0


def test_excerpt_similarity_uses_ngram_jaccard():
    a = _result(1, "Factura 245745 total 12.450 EUR")
    b = _result(2, "Factura 245745 total 12.450 USD")
    sim = _excerpt_similarity(a, b)
    # Single token difference -> very high but not 1.0.
    assert 0.5 < sim < 1.0


# ---------------------------------------------------------------------------
# mmr_rerank — the core algorithm
# ---------------------------------------------------------------------------


def test_mmr_returns_empty_for_empty_input():
    result = mmr_rerank([], top_k=5, lambda_param=0.7)
    assert result.results == []
    assert result.outcome == "empty"
    assert result.avg_pairwise_similarity == 0.0


def test_mmr_returns_empty_for_zero_top_k():
    candidates = [_result(1, "alpha"), _result(2, "beta")]
    result = mmr_rerank(candidates, top_k=0, lambda_param=0.7)
    assert result.results == []
    assert result.outcome == "passthrough"


def test_mmr_passes_through_when_pool_smaller_than_top_k():
    candidates = [_result(1, "alpha"), _result(2, "beta")]
    result = mmr_rerank(candidates, top_k=5, lambda_param=0.7)
    assert len(result.results) == 2
    assert result.outcome == "passthrough"


def test_mmr_passes_through_when_lambda_is_one():
    """``lambda=1`` reduces MMR to plain top-k-by-relevance."""
    candidates = [
        _result(1, "alpha alpha alpha", score=1.0),
        _result(2, "alpha alpha alpha", score=0.9),  # duplicate
        _result(3, "beta", score=0.8),
    ]
    result = mmr_rerank(candidates, top_k=2, lambda_param=1.0)
    assert [r.document_id for r in result.results] == [1, 2]
    # The outcome label distinguishes ``lambda=1`` (operator
    # explicitly disabled diversity) from a too-small pool;
    # the former gets ``passthrough_lambda_one`` so the admin
    # UI can show the metric clearly.
    assert result.outcome == "passthrough_lambda_one"


def test_mmr_diversifies_when_duplicates_present():
    """The classic MMR use-case: top-3 by relevance are three
    copies of the same paragraph. MMR swaps 2 of them for
    different documents."""
    duplicate_text = "Factura 245745 total 12.450 EUR cliente Acme"
    candidates = [
        _result(1, duplicate_text, score=1.0),
        _result(2, duplicate_text, score=0.95),  # near-duplicate of 1
        _result(3, duplicate_text, score=0.9),   # near-duplicate of 1
        _result(4, "Pedido PV26-020921 importe 3.200 EUR", score=0.85),
        _result(5, "Plano 1:50 superficie 80 m2", score=0.8),
    ]
    result = mmr_rerank(candidates, top_k=3, lambda_param=0.7)
    doc_ids = [r.document_id for r in result.results]
    # The first hit must be the most relevant (1). The second
    # and third should NOT be 2 and 3 (the duplicates); MMR
    # must pick 4 or 5 instead.
    assert doc_ids[0] == 1
    assert doc_ids[1] in (4, 5)
    assert doc_ids[2] in (4, 5)
    assert result.outcome == "diversified"
    # And the diversity metric must be higher than plain top-3
    # (which would have been 1.0 — three identical excerpts).
    assert result.avg_pairwise_similarity < 1.0


def test_mmr_picks_diverse_first_when_lambda_is_zero():
    """``lambda=0`` makes MMR pure diversity; the first hit
    is the seed, the rest are the most-novel candidates."""
    candidates = [
        _result(1, "Factura A", score=1.0),
        _result(2, "Factura A", score=0.9),  # duplicate of 1
        _result(3, "Pedido B", score=0.8),
        _result(4, "Plano C", score=0.7),
    ]
    result = mmr_rerank(candidates, top_k=3, lambda_param=0.0)
    doc_ids = [r.document_id for r in result.results]
    # First hit is the relevance seed (1). The next two
    # are the most-novel candidates (3 and 4), not the
    # duplicate (2).
    assert doc_ids[0] == 1
    assert doc_ids[1] != 2
    assert doc_ids[2] != 2
    assert result.outcome == "diversified"


def test_mmr_lambda_clamping():
    """``lambda > 1`` and ``lambda < 0`` are clamped to ``[0, 1]``
    so a typo in the settings does not crash the search."""
    candidates = [
        _result(1, "alpha", score=1.0),
        _result(2, "beta", score=0.5),
        _result(3, "gamma", score=0.3),
    ]
    # ``lambda=2.0`` clamps to ``1.0`` -> passthrough
    result_high = mmr_rerank(candidates, top_k=2, lambda_param=2.0)
    assert result_high.outcome in {"passthrough", "passthrough_lambda_one"}
    # ``lambda=-1.0`` clamps to ``0.0`` -> pure diversity
    result_low = mmr_rerank(candidates, top_k=2, lambda_param=-1.0)
    assert result_low.outcome == "diversified"


def test_mmr_preserves_count_when_top_k_exactly_equals_pool():
    candidates = [_result(1, "a"), _result(2, "b"), _result(3, "c")]
    result = mmr_rerank(candidates, top_k=3, lambda_param=0.7)
    # pool_size == top_k -> passthrough
    assert len(result.results) == 3
    assert result.outcome == "passthrough"


def test_mmr_returns_top_k_items():
    candidates = [_result(i, f"excerpt {i}") for i in range(10)]
    result = mmr_rerank(candidates, top_k=4, lambda_param=0.7)
    assert len(result.results) == 4


def test_mmr_avg_pairwise_similarity_within_bounds():
    candidates = [
        _result(1, "alpha", score=1.0),
        _result(2, "beta", score=0.5),
        _result(3, "gamma", score=0.3),
        _result(4, "delta", score=0.1),
    ]
    result = mmr_rerank(candidates, top_k=3, lambda_param=0.7)
    assert 0.0 <= result.avg_pairwise_similarity <= 1.0


def test_mmr_uses_custom_similarity_function():
    """The caller can plug in any similarity function that
    returns a value in [0, 1]."""
    candidates = [
        _result(1, "this is a long passage about the budget", score=1.0),
        _result(2, "this is a long passage about the budget", score=0.9),
        _result(3, "totally different content here", score=0.8),
    ]
    # Constant-zero similarity -> MMR picks by relevance only.
    result = mmr_rerank(
        candidates, top_k=2, lambda_param=0.7, similarity_fn=lambda a, b: 0.0
    )
    # Constant similarity is the same as relevance-only, which
    # is the "passthrough" branch (lambda=1 effectively).
    # We just assert the function ran without raising.
    assert len(result.results) == 2


# ---------------------------------------------------------------------------
# _average_pairwise_similarity helper
# ---------------------------------------------------------------------------


def test_average_pairwise_similarity_zero_for_single_result():
    assert _average_pairwise_similarity([], lambda a, b: 0.0) == 0.0
    assert _average_pairwise_similarity(
        [_result(1, "alpha")], lambda a, b: 0.0
    ) == 0.0


def test_average_pairwise_similarity_correct_for_three_results():
    candidates = [
        _result(1, "alpha"),
        _result(2, "alpha"),
        _result(3, "beta"),
    ]
    # (alpha, alpha) -> 1.0; (alpha, beta) -> 0; (alpha, beta) -> 0.
    avg = _average_pairwise_similarity(candidates, _excerpt_similarity)
    assert avg == pytest.approx(1.0 / 3.0, abs=0.05)


# ---------------------------------------------------------------------------
# Smoke: the metrics helper is exposed
# ---------------------------------------------------------------------------


def test_mmr_does_not_raise_on_pathological_input():
    """A defensive test: a single candidate with top_k=10 must
    not raise (we just return the candidate)."""
    result = mmr_rerank([_result(1, "alpha")], top_k=10, lambda_param=0.7)
    assert len(result.results) == 1
    assert result.outcome == "passthrough"
