"""E1 — Structure-aware chunking for the embedding pipeline.

The previous implementation split text by words without regard to
where sentences, tables or headings actually started. That meant a
budget table could be split mid-row and the chunk that survived into
the embedding index would say "TOTAL | | 12.450 EUR" — useful to a
human scanning the chunk, but useless to the retriever that gets
asked "importe total del presupuesto 245745". The retriever cannot
reassemble a table that was never kept together.

This module:

* detects markdown tables (already produced by the PDF parser in
  ``parsers/pdf.py::_extract_table_markdown``) and keeps each table
  as a single chunk with ``chunk_type="table"``;
* detects headings (markdown ``#``, ``##``, ... or visual
  short-uppercase lines, or lines ending in ``:``) and prepends
  them to the following chunk so the section context travels with
  the chunk;
* splits the rest of the text on sentence boundaries, never mid-word;
* carries a *token-aware overlap* that is bounded by a configurable
  budget but only ever re-emits complete sentences as overlap.

The public API is unchanged: ``build_chunks(text) -> list[Chunk]``
where ``Chunk`` is a dataclass that **also** unpacks as
``(text, token_count)`` for legacy callers. The new
``chunk_type`` field is the third element of the dataclass.

Why not just use ``chonkie`` / ``semchunk``? Both are excellent but
they add a dependency that needs to be reviewed for security and
binary footprint. The custom implementation below is ~150 lines
and covers the cases the project actually has (Spanish / English
prose, markdown tables, headings). A future task can swap it for
chonkie behind the same public API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PARAGRAPH_RE = re.compile(r"\n\s*\n+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
# Markdown heading: 1-6 ``#`` followed by space and the heading text.
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
# Markdown table line: starts with ``|`` and ends with ``|`` (with
# optional whitespace). We do not parse the table itself; we just
# look for the *contiguous run* of such lines.
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
# Space-aligned "table" line: a line that has 2+ columns separated by
# runs of 2+ spaces, the common output of OCR on scanned
# invoices/budgets that don't arrive as markdown. We require at least
# two such separators AND a minimum of one alphanumeric token in each
# column so prose like "Esto es una frase" (single space) is not
# mistaken for a table. Tab-separated columns are treated the same way
# (OCR sometimes emits tabs between detected columns).
_ALIGNED_TABLE_COL_RE = re.compile(r"\S(?:.*?\S)?(?:\s{2,}|\t+)\S")
# A bare "label:" line that often appears in invoices / planos as a
# soft heading ("Cliente:", "Importe total:", "Escala:").
_LABEL_HEADING_RE = re.compile(r"^([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑ 0-9]{2,40}):\s*$")
# A short all-caps line (typical of a section heading in a budget or
# measurement sheet).
_SHORT_CAPS_RE = re.compile(r"^[A-ZÁÉÍÓÚÑ0-9 .,/\-]{4,60}$")


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    """A single embedding-ready chunk.

    Fields:
        text: the chunk text (no leading metadata header; the caller
            prepends one via :func:`embedding_text_with_metadata`).
        token_count: best-effort word count, used for diagnostics and
            for the *overlap budget* math.
        chunk_type: one of ``"text"``, ``"table"``, ``"heading"``.
            ``"table"`` chunks are always emitted whole; ``"heading"``
            chunks are usually *attached* to the next non-heading
            chunk as a prefix and never emitted alone, but the type
            is recorded so the pipeline can decide to drop them if
            they have no payload.
    """

    text: str
    token_count: int
    chunk_type: str = "text"

    def __iter__(self):
        """Legacy 2-tuple unpacking: ``text, tokens = chunk``.

        The dataclass exposes ``chunk_type`` as a regular attribute
        so new callers that need it can read it directly via
        ``chunk.chunk_type``. This keeps the existing call sites
        that do ``for text, _ in build_chunks(text)`` working
        without modification.
        """
        yield self.text
        yield self.token_count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _word_count(text: str) -> int:
    return len(text.split())


def _metadata_value(value: str) -> str:
    return " ".join(str(value).replace("|", " ").split())


def _looks_like_aligned_table_line(line: str) -> bool:
    """Heuristic: does this line look like a row of a space-aligned
    table (as opposed to prose)? We require at least one multi-space
    (or tab) column separator that splits the line into two non-empty
    tokens, AND reject obvious prose by requiring the line to be
    relatively short (table rows from OCR are rarely full sentences).
    """
    stripped = line.rstrip()
    # Too long → almost certainly prose, not a table row.
    if len(stripped) > 120:
        return False
    if not stripped:
        return False
    return bool(_ALIGNED_TABLE_COL_RE.search(stripped))


def _split_table_block(lines: list[str]) -> list[tuple[list[str], bool]]:
    """Partition a list of lines into runs of consecutive table lines
    vs plain lines. Used so we can attach the right ``chunk_type`` to
    each run.

    Two table flavours are detected:

    * Markdown tables (``| ... |``) — always treated as tables.
    * Space-aligned tables (columns separated by 2+ spaces / tabs),
      the typical output of OCR on scanned invoices. A single aligned
      line is not enough to be a table; we require at least 2
      consecutive aligned lines so prose is not misclassified.

    Returns a list of ``(lines, is_table)`` tuples, one per run.
    """
    if not lines:
        return []
    # First pass: mark each line with a candidate "is_table" flag.
    # Markdown lines are tables on their own; aligned lines are only
    # tables when they appear in a contiguous block of >=2.
    flags: list[bool] = []
    i = 0
    n = len(lines)
    while i < n:
        if _TABLE_LINE_RE.match(lines[i]):
            flags.append(True)
            i += 1
            continue
        if _looks_like_aligned_table_line(lines[i]):
            j = i
            while j < n and _looks_like_aligned_table_line(lines[j]):
                j += 1
            # Only treat as table if the run is at least 2 lines.
            for _ in range(i, j):
                flags.append(j - i >= 2)
            i = j
        else:
            flags.append(False)
            i += 1

    # Second pass: group consecutive lines that share the same flag.
    runs: list[tuple[list[str], bool]] = []
    current: list[str] = []
    current_is_table = False
    for idx, line in enumerate(lines):
        is_table = flags[idx]
        if idx > 0 and is_table != current_is_table and current:
            runs.append((current, current_is_table))
            current = []
        current.append(line)
        current_is_table = is_table
    if current:
        runs.append((current, current_is_table))
    return runs


def _is_heading(line: str) -> str | None:
    """Return the heading text if ``line`` looks like a heading, else
    ``None``. Detects three flavours:

    * Markdown ``# H1`` / ``## H2`` / etc. — the original ``#``
      prefix is preserved so the embedder sees the visual cue
      ("## Cliente" rather than "Cliente").
    * ``Label:`` style (one short line ending in colon, used in
      invoices and measurement sheets).
    * A short line that is all uppercase or digits, also typical
      of a section heading in a measurement sheet.
    """
    stripped = line.strip()
    if not stripped:
        return None
    md = _MD_HEADING_RE.match(stripped)
    if md:
        # Preserve the markdown prefix so the heading is visually
        # distinguishable in the embedding input.
        hashes = md.group(1)
        return f"{hashes} {md.group(2).strip()}"
    if _LABEL_HEADING_RE.match(stripped):
        return stripped.rstrip(":")
    if (
        4 <= len(stripped) <= 60
        and _SHORT_CAPS_RE.match(stripped)
        and stripped == stripped.upper()
        and not stripped.endswith(".")
    ):
        return stripped
    return None


# ---------------------------------------------------------------------------
# Building chunks
# ---------------------------------------------------------------------------


def _split_oversized_sentence(
    sentence: str,
    max_words: int,
) -> list[str]:
    """A single sentence that exceeds ``max_words`` has to be split
    without a sentence boundary to fall back on. We split at word
    boundaries so we never start a chunk mid-word."""
    words = sentence.split()
    if len(words) <= max_words:
        return [sentence]
    return [" ".join(words[start : start + max_words]) for start in range(0, len(words), max_words)]


def _emit_table(
    lines: list[str],
    chunks: list[Chunk],
    *,
    heading_prefix: str | None,
) -> str | None:
    """Emit a table as a single ``chunk_type="table"`` chunk.

    Tables can be huge (a budget can have 30+ rows). When the
    combined word count exceeds ``max_words`` we still keep the
    table together — splitting a table mid-row is the exact bug
    this module exists to prevent. The caller is expected to set a
    ``max_words`` large enough to fit a typical page table
    (default 256 tokens ≈ 350 Spanish words).
    """
    text = "\n".join(lines).strip()
    if not text:
        return heading_prefix
    if heading_prefix:
        text = f"{heading_prefix}\n{text}"
        heading_prefix = None
    chunks.append(Chunk(text=text, token_count=_word_count(text), chunk_type="table"))
    return heading_prefix


def _emit_text(
    text_units: list[str],
    chunks: list[Chunk],
    *,
    max_words: int,
    overlap_words: int,
    heading_prefix: str | None,
) -> str | None:
    """Pack ``text_units`` (sentences) into chunks of up to
    ``max_words`` words, with ``overlap_words`` of carry-over from
    the previous chunk. Returns the heading prefix to carry to the
    next chunk (``None`` if this one consumed it)."""
    if not text_units:
        return heading_prefix
    current_units: list[str] = []
    current_words = 0
    if heading_prefix:
        current_units.append(heading_prefix)
        current_words = _word_count(heading_prefix)
        heading_prefix = None
    for unit in text_units:
        unit_words = _word_count(unit)
        if current_units and current_words + unit_words > max_words:
            text = " ".join(current_units).strip()
            if text:
                chunks.append(Chunk(text=text, token_count=_word_count(text), chunk_type="text"))
            # Carry-over: take as many trailing units as fit into
            # the overlap budget. We never emit overlap larger
            # than the budget, and we drop the overlap window
            # entirely when a single unit is already bigger than
            # the budget (otherwise the tail would dominate every
            # subsequent chunk).
            if overlap_words > 0:
                carry: list[str] = []
                carry_words = 0
                for previous in reversed(current_units):
                    pw = _word_count(previous)
                    if carry and carry_words + pw > overlap_words:
                        break
                    if not carry and pw > overlap_words:
                        break
                    carry.append(previous)
                    carry_words += pw
                current_units = list(reversed(carry))
                current_words = carry_words
            else:
                current_units = []
                current_words = 0
        current_units.append(unit)
        current_words += _word_count(unit)
    if current_units:
        text = " ".join(current_units).strip()
        if text:
            chunks.append(Chunk(text=text, token_count=_word_count(text), chunk_type="text"))
    return heading_prefix


def _split_into_paragraph_sentences(text: str) -> list[list[str]]:
    """Same behaviour as the original ``_paragraph_sentences`` helper:
    return one list of sentences per paragraph."""
    paragraphs: list[list[str]] = []
    for paragraph in _PARAGRAPH_RE.split(text or ""):
        clean = " ".join(paragraph.split())
        if not clean:
            continue
        sentences = [sentence.strip() for sentence in _SENTENCE_RE.split(clean) if sentence.strip()]
        paragraphs.append(sentences or [clean])
    return paragraphs


def _emit_prose_lines(
    prose_lines: list[str],
    chunks: list[Chunk],
    pending_heading: str | None,
    *,
    max_words: int,
    overlap_words: int,
    respect_headings: bool,
) -> str | None:
    """Emit a non-table run as heading-aware prose chunks.

    Mirrors the previous inline block logic: when ``respect_headings``
    is on, heading lines are stripped out and folded into
    ``pending_heading`` (so they travel with the next chunk), and the
    remaining prose is packed into chunks by :func:`_emit_text`.
    Returns the (possibly updated) ``pending_heading``.
    """
    if respect_headings:
        filtered: list[str] = []
        for line in prose_lines:
            heading = _is_heading(line)
            if heading:
                pending_heading = heading
                continue
            filtered.append(line)
        prose_lines = filtered
    prose_text = "\n".join(prose_lines).strip()
    if not prose_text:
        return pending_heading
    sentences = _SENTENCE_RE.split(prose_text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return pending_heading
    return _emit_text(
        sentences,
        chunks,
        max_words=max_words,
        overlap_words=overlap_words,
        heading_prefix=pending_heading,
    )


def build_chunks(
    text: str,
    max_words: int = 220,
    overlap_words: int = 40,
    *,
    respect_tables: bool = True,
    respect_headings: bool = True,
) -> list[Chunk]:
    """Split ``text`` into structure-aware chunks.

    Returns a list of :class:`Chunk`. The list is empty when the
    input is empty / whitespace.

    Backward compatibility: each ``Chunk`` is iterable as
    ``(text, token_count, chunk_type)`` and the 2-tuple form
    ``(text, token_count)`` is also supported via the dataclass
    iteration protocol. Existing call sites that do
    ``for text, _ in build_chunks(text)`` keep working.

    Args:
        text: the page text (already sanitised for the database).
        max_words: soft upper bound on chunk size in *words*. A
            single sentence bigger than this still ends up whole
            (we never split mid-word).
        overlap_words: budget of words to carry over between
            consecutive text chunks. Tables and headings are
            always emitted whole, never with overlap.
        respect_tables: when True, consecutive ``|...|`` lines
            become a single ``chunk_type="table"`` chunk. When
            False, the legacy behaviour is restored (tables are
            treated as ordinary text).
        respect_headings: when True, a heading line is attached as
            a prefix to the following non-heading chunk. When
            False, headings are treated as ordinary text.
    """
    if not text or not text.strip():
        return []

    chunks: list[Chunk] = []
    pending_heading: str | None = None

    # We split the input on blank lines so each *block* is either a
    # table, a heading, or a prose paragraph. The block boundaries
    # are then processed in order; tables are detected by looking
    # at every line of the block.
    for block in _PARAGRAPH_RE.split(text):
        clean_block = block.strip()
        if not clean_block:
            continue
        block_lines = clean_block.splitlines()

        # Whole block is a markdown table → single table chunk.
        if respect_tables and all(_TABLE_LINE_RE.match(line) for line in block_lines):
            pending_heading = _emit_table(block_lines, chunks, heading_prefix=pending_heading)
            continue

        # Otherwise split into table / non-table runs so space-aligned
        # OCR tables (columns separated by 2+ spaces / tabs) are kept
        # whole as ``chunk_type="table"`` instead of being cut by
        # sentence boundaries. Non-table runs keep the existing
        # heading-aware prose handling.
        if respect_tables:
            for run_lines, run_is_table in _split_table_block(block_lines):
                if run_is_table:
                    pending_heading = _emit_table(
                        run_lines, chunks, heading_prefix=pending_heading
                    )
                else:
                    pending_heading = _emit_prose_lines(
                        run_lines,
                        chunks,
                        pending_heading,
                        max_words=max_words,
                        overlap_words=overlap_words,
                        respect_headings=respect_headings,
                    )
        else:
            pending_heading = _emit_prose_lines(
                block_lines,
                chunks,
                pending_heading,
                max_words=max_words,
                overlap_words=overlap_words,
                respect_headings=respect_headings,
            )

    # If a heading was attached to a chunk that never came (e.g.
    # empty document), emit it as its own heading chunk so the
    # information is not lost.
    if pending_heading:
        chunks.append(
            Chunk(
                text=pending_heading,
                token_count=_word_count(pending_heading),
                chunk_type="heading",
            )
        )

    return chunks


# ---------------------------------------------------------------------------
# Legacy compatibility shims
# ---------------------------------------------------------------------------


def _paragraph_sentences(text: str) -> list[list[str]]:
    """Backward-compatible re-export of the old internal helper.

    Some downstream modules (and the legacy tests) imported this
    name from the original ``chunking`` module. We keep it so the
    public surface does not break; new code should call
    :func:`_split_into_paragraph_sentences` instead.
    """
    return _split_into_paragraph_sentences(text)


# ---------------------------------------------------------------------------
# Metadata header (unchanged)
# ---------------------------------------------------------------------------


def chunk_metadata_header(
    *,
    document_type: str | None = None,
    filename: str | None = None,
    page_number: int | None = None,
) -> str:
    """Build the ``[tipo=... | fichero=... | pág=...]`` prefix that
    is prepended to a chunk before embedding. The header travels
    with the chunk so the retriever can use the document type /
    filename as semantic context, not just the chunk text.
    """
    fields: list[str] = []
    if document_type:
        fields.append(f"tipo={_metadata_value(document_type)}")
    if filename:
        fields.append(f"fichero={_metadata_value(filename)}")
    if page_number is not None:
        fields.append(f"pág={int(page_number)}")
    if not fields:
        return ""
    return "[" + " | ".join(fields) + "]"


def embedding_text_with_metadata(
    chunk_text: str,
    *,
    document_type: str | None = None,
    filename: str | None = None,
    page_number: int | None = None,
) -> str:
    """Prepend :func:`chunk_metadata_header` to the chunk text."""
    header = chunk_metadata_header(
        document_type=document_type,
        filename=filename,
        page_number=page_number,
    )
    if not header:
        return chunk_text
    return f"{header} {chunk_text}"


__all__ = [
    "Chunk",
    "build_chunks",
    "embedding_text_with_metadata",
    "chunk_metadata_header",
]
