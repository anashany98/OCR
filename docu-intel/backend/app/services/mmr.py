"""E5 — Maximal Marginal Relevance (MMR) reranker for the hybrid retriever.

The cross-encoder reranker (BGE-reranker-v2-m3) improves precision
but does nothing for *diversity*. When the top of the retrieval
list is dominated by chunks from a single document — or by
chunks that paraphrase the same passage — the user sees a
top-k that is internally redundant. MMR (Carbonell & Goldstein,
1998) addresses this by re-ordering the candidates so that the
score of a hit is a weighted sum of its relevance to the query
**and** its novelty relative to the hits already chosen.

The classic MMR score for a candidate ``d`` given the selected
set ``S`` is::

    mmr(d) = lambda * relevance(d) - (1 - lambda) * max_{s in S} similarity(d, s)

``lambda = 1`` reduces MMR to plain relevance ranking (no
diversity). ``lambda = 0`` makes it pure diversity (ignores the
query). The sweet spot for a RAG retrieval is usually
``lambda in [0.6, 0.8]``: relevance dominates but the second /
third hit in a near-duplicate cluster is swapped for a chunk
from a different document.

Similarity is computed over the chunk excerpt (no extra
embedding model needed). We use a *character n-gram Jaccard*
similarity: cheap, language-agnostic, and correlates well enough
with semantic similarity for the "are these two passages
saying the same thing?" question. The caller can swap the
similarity function for an embedding-based one when the
operator needs it.

The function is **fail-safe**: when the candidate pool is too
small (less than ``top_k``) or when the diversity threshold is
not met, MMR returns the top-k by relevance unchanged. The
retrieval that depends on it never breaks.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.metrics import track_mmr

if TYPE_CHECKING:
    from app.services.search_service import SearchResult

logger = logging.getLogger("app.services.mmr")


# ---------------------------------------------------------------------------
# Similarity function
# ---------------------------------------------------------------------------


# Default n-gram length. Shorter n-grams are noisier (single
# characters are useless); longer n-grams are too sparse to
# fire across paraphrases. ``3`` is a good middle ground for
# mixed-length Spanish / English prose.
_DEFAULT_NGRAM_LEN = 3


def _ngrams(text: str, n: int = _DEFAULT_NGRAM_LEN) -> set[str]:
    """Return the set of *character* n-grams of length ``n`` in
    ``text``. The text is lower-cased and stripped of leading /
    trailing whitespace before tokenisation.
    """
    if not text:
        return set()
    cleaned = re.sub(r"\s+", " ", text.lower().strip())
    if len(cleaned) < n:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + n] for i in range(len(cleaned) - n + 1)}


def jaccard_ngram_similarity(left: str, right: str, *, n: int = _DEFAULT_NGRAM_LEN) -> float:
    """Character-n-gram Jaccard similarity between two strings.

    Returns a value in ``[0, 1]``. ``1.0`` means the two
    passages are identical (or one is a subset of the other);
    ``0.0`` means they share no n-gram. Two completely
    different paragraphs will typically score below ``0.3``.
    """
    a = _ngrams(left, n=n)
    b = _ngrams(right, n=n)
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    if not union:
        return 0.0
    return len(intersection) / len(union)


def _excerpt_similarity(left: "SearchResult", right: "SearchResult") -> float:
    """Default similarity function: n-gram Jaccard on the chunk
    excerpts. Falls back to ``0.0`` when either excerpt is empty
    (e.g. a chunk whose text is only a heading or only a
    table — these get a free pass, MMR treats them as novel)."""
    return jaccard_ngram_similarity(left.excerpt or "", right.excerpt or "")


# Type alias for the similarity function. The MMR loop only
# needs (candidate, selected) -> float; the caller can plug in
# any backend that produces a value in [0, 1].
SimilarityFn = Callable[["SearchResult", "SearchResult"], float]


# ---------------------------------------------------------------------------
# MMR algorithm
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MMRResult:
    """The MMR rerank outcome.

    Attributes:
        results: the re-ordered top-k candidates.
        avg_pairwise_similarity: the average n-gram Jaccard
            similarity between the chosen hits, reported so the
            admin UI can see how much diversity the run actually
            achieved. ``0.0`` means perfect diversity (no two
            hits are paraphrases); ``1.0`` means the top-k is
            five copies of the same paragraph.
        outcome: ``"diversified"`` when MMR re-ordered the input,
            ``"passthrough"`` when it returned the top-k by
            relevance unchanged (input too small or lambda=1),
            ``"empty"`` when the input was empty.
    """

    results: list["SearchResult"]
    avg_pairwise_similarity: float
    outcome: str


def mmr_rerank(
    candidates: Iterable["SearchResult"],
    *,
    top_k: int = 5,
    lambda_param: float = 0.7,
    similarity_fn: SimilarityFn | None = None,
) -> MMRResult:
    """Apply Maximal Marginal Relevance to ``candidates`` and
    return the top-k most relevant-yet-diverse items.

    Args:
        candidates: the input list. The *first* element is
            assumed to be the most relevant (the function does
            not re-sort; the upstream reranker already did). The
            iterable is consumed once into a list so the loop
            below can iterate it multiple times safely.
        top_k: how many hits to return.
        lambda_param: the relevance weight. ``1.0`` = pure
            relevance; ``0.0`` = pure diversity. Values outside
            ``[0, 1]`` are clamped.
        similarity_fn: optional override. When ``None`` we use
            the n-gram Jaccard default.

    Returns:
        :class:`MMRResult` with the re-ordered list and a
        ``avg_pairwise_similarity`` diagnostic.
    """
    pool = list(candidates)
    sim = similarity_fn or _excerpt_similarity
    safe_lambda = max(0.0, min(1.0, float(lambda_param)))

    if not pool:
        track_mmr("empty", avg_similarity=0.0)
        return MMRResult(results=[], avg_pairwise_similarity=0.0, outcome="empty")

    if top_k <= 0:
        track_mmr("passthrough", avg_similarity=0.0)
        return MMRResult(results=[], avg_pairwise_similarity=0.0, outcome="passthrough")

    # When the pool is smaller than top_k, or when relevance
    # dominates (lambda = 1), MMR has nothing to diversify. We
    # return the top-k by relevance unchanged so the caller
    # never loses a hit.
    if len(pool) <= top_k or safe_lambda >= 1.0:
        top = pool[:top_k]
        avg_sim = _average_pairwise_similarity(top, sim)
        outcome = "passthrough" if len(pool) <= top_k else "passthrough_lambda_one"
        track_mmr(outcome, avg_similarity=avg_sim)
        return MMRResult(results=top, avg_pairwise_similarity=avg_sim, outcome=outcome)

    # Pure-diversity mode: ignore relevance entirely. This is
    # the "show me 5 different documents" UX; the caller can
    # pin it via ``search_mmr_lambda=0.0``.
    if safe_lambda <= 0.0:
        # Greedy: pick the first element as the seed (by
        # relevance), then add the one with the *lowest* max
        # similarity to the selected set, until we have ``top_k``.
        selected: list["SearchResult"] = [pool[0]]
        remaining = pool[1:]
        while len(selected) < top_k and remaining:
            # Find the candidate with the minimum max-similarity
            # to the selected set; pop it.
            best_idx = 0
            best_score = float("inf")
            for i, cand in enumerate(remaining):
                max_sim = max((sim(cand, s) for s in selected), default=0.0)
                if max_sim < best_score:
                    best_score = max_sim
                    best_idx = i
            selected.append(remaining.pop(best_idx))
        avg_sim = _average_pairwise_similarity(selected, sim)
        track_mmr("diversified", avg_similarity=avg_sim)
        return MMRResult(results=selected, avg_pairwise_similarity=avg_sim, outcome="diversified")

    # Standard MMR loop. We track each candidate's ``relevance``
    # as its position in the input list (the upstream reranker
    # already ordered by relevance, so we use 1/rank as the
    # relevance score; MMR only needs the relative ordering
    # to be respected).
    n = len(pool)
    relevance = [1.0 / (i + 1) for i in range(n)]
    selected: list["SearchResult"] = []
    selected_indices: list[int] = []
    remaining_indices = list(range(n))

    while len(selected) < top_k and remaining_indices:
        best_idx = remaining_indices[0]
        best_score = -float("inf")
        for idx in remaining_indices:
            cand = pool[idx]
            max_sim = max(
                (sim(cand, pool[s]) for s in selected_indices),
                default=0.0,
            )
            mmr_score = safe_lambda * relevance[idx] - (1.0 - safe_lambda) * max_sim
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx
        selected.append(pool[best_idx])
        selected_indices.append(best_idx)
        remaining_indices.remove(best_idx)

    avg_sim = _average_pairwise_similarity(selected, sim)
    track_mmr("diversified", avg_similarity=avg_sim)
    return MMRResult(results=selected, avg_pairwise_similarity=avg_sim, outcome="diversified")


def _average_pairwise_similarity(
    results: list["SearchResult"],
    sim: SimilarityFn,
) -> float:
    """Return the average pairwise similarity across the chosen
    hits, used to report how diverse the MMR pick really was.

    Returns ``0.0`` when fewer than 2 results are present (the
    average is undefined)."""
    if len(results) < 2:
        return 0.0
    total = 0.0
    count = 0
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            total += sim(results[i], results[j])
            count += 1
    return total / count if count else 0.0


__all__ = [
    "MMRResult",
    "mmr_rerank",
    "jaccard_ngram_similarity",
    "_excerpt_similarity",
]
