"""Tests for E6 — contextual compression.

The compressor is pure (no DB, no LLM) and scores each sentence
in a chunk by its keyword overlap with the query. The tests pin
the contract so a future refactor cannot silently change the
compression rules.
"""
from __future__ import annotations

import pytest

from app.services.contextual_compression import (
    CompressedChunk,
    CompressionReport,
    compress_chunks,
)


# ---------------------------------------------------------------------------
# compress_chunks
# ---------------------------------------------------------------------------


def test_compress_chunks_returns_all_when_no_query_words():
    chunks = [{"excerpt": "First sentence. Second sentence."}]
    report = compress_chunks(chunks, query="", min_keyword_overlap=0.5)
    assert len(report.chunks) == 1
    assert report.chunks[0].sentences_kept == 2


def test_compress_chunks_returns_all_when_overlap_zero():
    chunks = [{"excerpt": "First sentence. Second sentence."}]
    report = compress_chunks(chunks, query="presupuesto", min_keyword_overlap=0.0)
    assert len(report.chunks) == 1
    assert report.chunks[0].sentences_kept == 2


def test_compress_chunks_filters_by_keyword_overlap():
    chunks = [
        {
            "excerpt": (
                "El presupuesto 245745 tiene un importe total de 12.450 EUR. "
                "El cliente se llama García. "
                "El color del logo es azul."
            )
        }
    ]
    report = compress_chunks(
        chunks,
        query="importe presupuesto 245745",
        min_keyword_overlap=0.5,
    )
    # "importe presupuesto 245745" = 3 words. The first sentence
    # has all 3 → kept. The second has 0 → dropped. The third
    # has 0 → dropped.
    assert report.chunks[0].sentences_kept == 1
    assert "importe" in report.chunks[0].compressed_text


def test_compress_chunks_respects_max_sentences():
    chunks = [
        {
            "excerpt": (
                "Sentence one about presupuesto. "
                "Sentence two about presupuesto. "
                "Sentence three about presupuesto. "
                "Sentence four about presupuesto."
            )
        }
    ]
    report = compress_chunks(
        chunks,
        query="presupuesto",
        min_keyword_overlap=0.0,
        max_sentences_per_chunk=2,
    )
    assert report.chunks[0].sentences_kept == 2


def test_compress_chunks_handles_empty_excerpt():
    chunks = [{"excerpt": ""}]
    report = compress_chunks(chunks, query="test")
    assert len(report.chunks) == 1
    assert report.chunks[0].compressed_text == ""


def test_compress_chunks_handles_missing_excerpt():
    chunks = [{"document_id": 1}]
    report = compress_chunks(chunks, query="test")
    assert len(report.chunks) == 1
    assert report.chunks[0].compressed_text == ""


def test_compress_chunks_handles_no_chunks():
    report = compress_chunks([], query="test")
    assert len(report.chunks) == 0
    assert report.compression_ratio == 1.0


def test_compress_chunks_compression_ratio_less_than_one():
    chunks = [
        {
            "excerpt": (
                "Presupuesto 245745 por importe 12.450 EUR. "
                "El cliente se llama García. "
                "El color del logo es azul. "
                "La factura fue emitida el 12 de marzo."
            )
        }
    ]
    report = compress_chunks(
        chunks,
        query="importe presupuesto",
        min_keyword_overlap=0.5,
    )
    assert report.compression_ratio < 1.0


def test_compress_chunks_preserves_order():
    """The compressor must keep the sentences in their original
    order, not the score order."""
    chunks = [
        {
            "excerpt": (
                "First about presupuesto. "
                "Second about nothing. "
                "Third about presupuesto again."
            )
        }
    ]
    report = compress_chunks(
        chunks,
        query="presupuesto",
        min_keyword_overlap=0.5,
    )
    compressed = report.chunks[0].compressed_text
    # The first sentence must come before the third.
    assert compressed.index("First") < compressed.index("Third")


def test_compress_chunks_multiple_chunks():
    chunks = [
        {"excerpt": "Presupuesto 245745 total 12.450 EUR."},
        {"excerpt": "Pedido PV26-020921 importe 3.200 EUR."},
        {"excerpt": "Plano DTM-003 escala 1:50."},
    ]
    report = compress_chunks(
        chunks,
        query="presupuesto importe",
        min_keyword_overlap=0.5,
    )
    assert len(report.chunks) == 3


def test_compress_chunks_report_aggregates():
    chunks = [
        {"excerpt": "A B C."},
        {"excerpt": "D E F."},
    ]
    report = compress_chunks(chunks, query="", min_keyword_overlap=0.0)
    assert report.total_original_chars > 0
    assert report.total_compressed_chars > 0
    assert 0.0 < report.compression_ratio <= 1.0
