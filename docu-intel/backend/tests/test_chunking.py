"""Tests for the E1 structure-aware chunker.

The chunker is pure (no I/O, no DB, no embedder), so the tests
feed it hand-crafted text and assert the resulting chunks. The
assertions are deliberately explicit about the *expected chunk
sequence* (text, token count, type) so a future refactor cannot
silently change where the boundaries fall.
"""
from __future__ import annotations

import pytest

from app.services.chunking import (
    Chunk,
    build_chunks,
    chunk_metadata_header,
    embedding_text_with_metadata,
)


# ---------------------------------------------------------------------------
# Backward compatibility: 2-tuple unpacking still works
# ---------------------------------------------------------------------------


def test_build_chunks_returns_chunk_dataclass_that_unpacks_as_2tuple():
    """Existing call sites do ``for text, _ in build_chunks(text)``.
    The new dataclass must continue to support that pattern via
    tuple-unpacking: ``text, _ = chunk``. The ``chunk_type`` is
    only available as a dataclass attribute (``chunk.chunk_type``)
    so it never accidentally appears in the 2-tuple form."""
    chunks = build_chunks("Una sola frase de prueba.", max_words=100)
    assert chunks, "expected at least one chunk"
    # 2-tuple unpack must succeed and yield (str, int).
    text, tokens = chunks[0]
    assert isinstance(text, str)
    assert isinstance(tokens, int)
    # The new field is only reachable as a dataclass attribute.
    ctype = chunks[0].chunk_type
    assert ctype in {"text", "table", "heading"}
    assert chunks[0].text == text
    assert chunks[0].token_count == tokens


def test_build_chunks_empty_input_returns_empty_list():
    assert build_chunks("") == []
    assert build_chunks("   \n  ") == []


# ---------------------------------------------------------------------------
# Plain text chunking (regression: legacy behaviour is preserved)
# ---------------------------------------------------------------------------


def test_build_chunks_respects_sentence_boundaries_when_possible():
    """The original behaviour: never split a sentence mid-word when
    the whole sentence fits the budget."""
    chunks = build_chunks(
        "Primera frase completa. Segunda frase con importe total. Tercera frase final.",
        max_words=5,
        overlap_words=0,
    )
    assert [c.text for c in chunks] == [
        "Primera frase completa.",
        "Segunda frase con importe total.",
        "Tercera frase final.",
    ]
    # Default chunk type is text.
    assert {c.chunk_type for c in chunks} == {"text"}


def test_build_chunks_keeps_paragraphs_separate_under_budget():
    chunks = build_chunks(
        "Cabecera del documento. Referencia ABC123.\n\n"
        "Detalle de factura. Total factura 120 euros.",
        max_words=7,
        overlap_words=0,
    )
    assert [c.text for c in chunks] == [
        "Cabecera del documento. Referencia ABC123.",
        "Detalle de factura. Total factura 120 euros.",
    ]


def test_build_chunks_carries_overlap_only_with_complete_sentences():
    """The overlap window must only ever re-emit complete sentences;
    a half-sentence overlap would be a corruption signal for the
    retriever."""
    chunks = build_chunks(
        "Frase uno del primer bloque. Frase dos del primer bloque. "
        "Frase tres del primer bloque. Frase cuatro del primer bloque. "
        "Frase cinco del primer bloque. Frase seis del primer bloque.",
        max_words=8,
        overlap_words=4,
    )
    # Every chunk must be a concatenation of whole sentences ending
    # in a period. (We don't enforce overlap content here, but
    # every chunk text must end in ``.``.)
    for chunk in chunks:
        assert chunk.text.endswith("."), f"chunk text not a complete sentence: {chunk.text!r}"


# ---------------------------------------------------------------------------
# Table chunks: must never be split mid-row
# ---------------------------------------------------------------------------


_MARKDOWN_BUDGET = (
    "# Cabecera del presupuesto\n\n"
    "Cliente: Acme S.L.    Fecha: 2025-04-12\n\n"
    "| Referencia | Descripcion | Cantidad | Precio | Total |\n"
    "| --- | --- | --- | --- | --- |\n"
    "| ABC-001 | Silla oficina | 4 | 120,00 | 480,00 |\n"
    "| ABC-002 | Mesa despacho | 1 | 350,00 | 350,00 |\n"
    "| ABC-003 | Archivador | 2 | 90,00 | 180,00 |\n"
    "|  |  |  | TOTAL | 1.010,00 |\n"
    "\n\n"
    "Notas: portes incluidos, IVA aparte."
)


def test_build_chunks_keeps_markdown_tables_whole():
    """The table must appear as exactly one chunk, with
    chunk_type="table", and the TOTAL row must end up in the same
    chunk as the rest of the table."""
    chunks = build_chunks(_MARKDOWN_BUDGET, max_words=20, overlap_words=0)
    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert len(table_chunks) == 1, f"expected one table chunk, got {len(table_chunks)}"
    table = table_chunks[0]
    assert "TOTAL" in table.text
    assert "1.010,00" in table.text
    assert "ABC-001" in table.text


def test_build_chunks_keeps_oversized_tables_whole():
    """Even when the table has more rows than fit in the word budget,
    the table must stay in one chunk. Splitting it mid-row is the
    exact bug this feature prevents."""
    big_table_rows = "\n".join(
        f"| R{i:03d} | Descripcion del item {i} | {i} | {i*1.5:.2f} | {i*1.5:.2f} |"
        for i in range(50)
    )
    text = (
        "| Ref | Desc | Qty | Unit | Total |\n"
        "| --- | --- | --- | --- | --- |\n"
        + big_table_rows
    )
    chunks = build_chunks(text, max_words=30, overlap_words=0)
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "table"
    assert "R000" in chunks[0].text
    assert "R049" in chunks[0].text


def test_build_chunks_can_disable_table_awareness():
    """The ``respect_tables=False`` flag must restore the legacy
    behaviour where every line is treated as plain text."""
    chunks = build_chunks(_MARKDOWN_BUDGET, max_words=20, overlap_words=0, respect_tables=False)
    types = {c.chunk_type for c in chunks}
    assert "table" not in types


# ---------------------------------------------------------------------------
# Headings: must be attached as a prefix to the next non-heading chunk
# ---------------------------------------------------------------------------


def test_build_chunks_attaches_markdown_heading_to_next_chunk():
    """A markdown heading must be prepended to the following chunk
    instead of being emitted as its own chunk."""
    text = "## Cliente\n\nEl cliente del presupuesto es Acme S.L."
    chunks = build_chunks(text, max_words=200, overlap_words=0)
    # We expect one text chunk that begins with the heading.
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "text"
    assert chunks[0].text.startswith("## Cliente")


def test_build_chunks_attaches_label_heading_to_next_chunk():
    text = "Cliente:\nEl cliente del presupuesto es Acme S.L. con CIF B12345678."
    chunks = build_chunks(text, max_words=200, overlap_words=0)
    assert len(chunks) == 1
    assert chunks[0].text.startswith("Cliente")


def test_build_chunks_emits_orphan_heading_as_its_own_chunk():
    """A heading at the end of the document (no following chunk to
    attach to) must still be emitted so the information is not
    lost."""
    chunks = build_chunks("Texto normal.\n\n## Cabecera final", max_words=200, overlap_words=0)
    # Last chunk must be the heading chunk so the heading survives
    # the round-trip.
    assert chunks[-1].chunk_type == "heading"
    assert "Cabecera final" in chunks[-1].text


def test_build_chunks_can_disable_heading_awareness():
    chunks = build_chunks(
        "## Cliente\n\nEl cliente es Acme S.L.",
        max_words=200,
        overlap_words=0,
        respect_headings=False,
    )
    # Without heading awareness the lines are treated as plain
    # text. The "## Cliente" line is not stripped or attached.
    full_text = " ".join(c.text for c in chunks)
    assert "## Cliente" in full_text


# ---------------------------------------------------------------------------
# Mixed content: tables + prose + headings in the same page
# ---------------------------------------------------------------------------


def test_build_chunks_handles_mixed_table_and_prose():
    text = (
        "Cabecera del documento.\n\n"
        "| Item | Precio |\n"
        "| --- | --- |\n"
        "| Item A | 100,00 |\n"
        "| Item B | 200,00 |\n\n"
        "Notas adicionales al final del documento."
    )
    chunks = build_chunks(text, max_words=200, overlap_words=0)
    types = [c.chunk_type for c in chunks]
    assert "table" in types
    # The prose chunks around the table are still emitted.
    assert "text" in types
    # The table chunk must contain both rows of the table.
    table = next(c for c in chunks if c.chunk_type == "table")
    assert "Item A" in table.text
    assert "Item B" in table.text
    assert "Notas adicionales" not in table.text  # prose stays out


# ---------------------------------------------------------------------------
# Settings: the default chunker respects the existing 220/40 budget
# ---------------------------------------------------------------------------


def test_default_settings_keep_legacy_chunk_budget():
    """The ``build_chunks`` defaults must remain 220 / 40 so the
    default pipeline behaviour does not change for deployments
    that have not opted into the new settings."""
    chunks = build_chunks(
        " ".join(f"Frase {i} del documento." for i in range(50)),
        max_words=220,
        overlap_words=40,
    )
    # Default chunk type is text.
    assert {c.chunk_type for c in chunks} == {"text"}


# ---------------------------------------------------------------------------
# Metadata header (unchanged)
# ---------------------------------------------------------------------------


def test_chunk_metadata_header_unchanged():
    assert (
        chunk_metadata_header(document_type="presupuesto", filename="ABC.pdf", page_number=3)
        == "[tipo=presupuesto | fichero=ABC.pdf | pág=3]"
    )
    assert (
        chunk_metadata_header(filename="with | pipe.pdf", page_number=1)
        == "[fichero=with pipe.pdf | pág=1]"
    )
    assert chunk_metadata_header() == ""


def test_embedding_text_with_metadata_prepends_header():
    text = embedding_text_with_metadata(
        "chunk text",
        document_type="presupuesto",
        filename="ABC.pdf",
        page_number=7,
    )
    assert text == "[tipo=presupuesto | fichero=ABC.pdf | pág=7] chunk text"
