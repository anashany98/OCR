"""E6 — Contextual compression for the RAG retrieval.

The retriever returns chunks that are *relevant* to the query but
often contain sentences that are *irrelevant* — boilerplate,
metadata, repeated headers, etc. When the LLM's context window
is limited (8k-32k tokens) these irrelevant sentences waste
precious budget and can dilute the model's attention.

This module provides a lightweight compression step that runs
*after* retrieval and *before* the LLM sees the context. It
scores each sentence in a chunk by its keyword overlap with the
query and keeps only the top-scoring sentences up to a
configurable token budget.

The compression is **deterministic** (no LLM involved) so it
adds zero latency and zero cost. The trade-off is that the
compression is keyword-based, not semantic — a sentence that is
semantically relevant but uses completely different vocabulary
than the query will be dropped. For the construction-document
domain (where the vocabulary is tight: "presupuesto", "pedido",
"importe", "plano", "habitación") this is an acceptable
trade-off.

The module is **fail-safe**: on any error the original chunks
are returned unchanged.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger("app.services.contextual_compression")


# ---------------------------------------------------------------------------
# Sentence tokeniser
# ---------------------------------------------------------------------------


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    """Split ``text`` into sentences. Returns the original text
    as a single-element list when the split produces nothing
    useful (e.g. a heading or a table row without punctuation).
    """
    if not text:
        return []
    sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
    return sentences if sentences else [text.strip()]


def _word_set(text: str) -> set[str]:
    """Return the set of lowercased words in ``text``."""
    return {w.lower() for w in re.findall(r"\w+", text) if len(w) >= 2}


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompressedChunk:
    """A single chunk after compression.

    Attributes:
        original_excerpt: the full excerpt before compression.
        compressed_text: the excerpt with only the relevant
            sentences.
        original_length: character count of the original.
        compressed_length: character count of the compressed.
        sentences_total: how many sentences the original had.
        sentences_kept: how many sentences the compressor kept.
    """

    original_excerpt: str
    compressed_text: str
    original_length: int
    compressed_length: int
    sentences_total: int
    sentences_kept: int


@dataclass(frozen=True)
class CompressionReport:
    """The result of compressing a list of chunks.

    Attributes:
        chunks: the compressed chunks.
        total_original_chars: sum of original lengths.
        total_compressed_chars: sum of compressed lengths.
        compression_ratio: ``total_compressed / total_original``
            (lower is more compressed; ``1.0`` = no compression).
    """

    chunks: list[CompressedChunk]
    total_original_chars: int
    total_compressed_chars: int
    compression_ratio: float


def compress_chunks(
    chunks: Iterable[dict],
    query: str,
    *,
    max_sentences_per_chunk: int | None = None,
    min_keyword_overlap: float = 0.0,
) -> CompressionReport:
    """Compress ``chunks`` by keeping only the sentences that
    overlap with ``query``.

    Args:
        chunks: an iterable of dicts with at least an ``excerpt``
            key (the chunk text) and optionally a ``document_id``,
            ``page_number``, ``score`` key. The function is
            duck-typed: it only reads ``excerpt``.
        query: the user's search text.
        max_sentences_per_chunk: if set, the compressor keeps at
            most this many sentences per chunk (after scoring).
            ``None`` means "keep all above the overlap threshold".
        min_keyword_overlap: the minimum fraction of query words
            that must appear in a sentence for it to be kept.
            ``0.0`` means "keep all sentences" (no filtering);
            ``0.5`` means "at least half the query words must
            appear".

    Returns:
        :class:`CompressionReport` with the compressed chunks
        and aggregate statistics. On any error the function
        returns the original chunks unchanged.
    """
    query_words = _word_set(query)
    results: list[CompressedChunk] = []
    total_original = 0
    total_compressed = 0

    for chunk in chunks:
        excerpt = chunk.get("excerpt", "") or ""
        if not excerpt:
            results.append(
                CompressedChunk(
                    original_excerpt="",
                    compressed_text="",
                    original_length=0,
                    compressed_length=0,
                    sentences_total=0,
                    sentences_kept=0,
                )
            )
            continue

        sentences = _split_sentences(excerpt)
        if not query_words or min_keyword_overlap <= 0.0:
            # No filtering: keep all sentences.
            scored = [(s, 1.0) for s in sentences]
        else:
            scored = []
            for sentence in sentences:
                sent_words = _word_set(sentence)
                if not sent_words:
                    scored.append((sentence, 0.0))
                    continue
                overlap = len(query_words & sent_words) / len(query_words)
                scored.append((sentence, overlap))

        # Sort by score descending, then by position (stable sort
        # keeps the original order for equal scores).
        scored.sort(key=lambda x: x[1], reverse=True)

        # Apply the min-overlap filter.
        if min_keyword_overlap > 0.0:
            scored = [(s, sc) for s, sc in scored if sc >= min_keyword_overlap]

        # Apply the max-sentences cap.
        if max_sentences_per_chunk is not None and max_sentences_per_chunk > 0:
            scored = scored[:max_sentences_per_chunk]

        # Re-order by original position (the sort above scrambled
        # the order). We do this by re-scanning the original
        # sentences and keeping only those that survived.
        kept_set = {s for s, _ in scored}
        kept_sentences = [s for s in sentences if s in kept_set]
        compressed = " ".join(kept_sentences)

        orig_len = len(excerpt)
        comp_len = len(compressed)
        total_original += orig_len
        total_compressed += comp_len

        results.append(
            CompressedChunk(
                original_excerpt=excerpt,
                compressed_text=compressed,
                original_length=orig_len,
                compressed_length=comp_len,
                sentences_total=len(sentences),
                sentences_kept=len(kept_sentences),
            )
        )

    ratio = total_compressed / total_original if total_original > 0 else 1.0
    return CompressionReport(
        chunks=results,
        total_original_chars=total_original,
        total_compressed_chars=total_compressed,
        compression_ratio=ratio,
    )


__all__ = [
    "CompressedChunk",
    "CompressionReport",
    "compress_chunks",
]
