"""Block 5 — RAG anti-hallucination regression tests.

The :func:`app.ai.validation.response_fabricates_documents`
heuristic is a **mitigation, not a guarantee** (see the
function docstring). These tests pin two specific cases
that the user flagged as broken before Block 5:

1. **False positive** — a valid response that was being
   rejected because the comparison was too strict. The
   example: a context that lists an amount as ``5000.00
   EUR`` and an answer that re-states it as ``5.000,00 EUR``
   (European formatting) or with a filename that contains
   internal spaces (``presupuesto 2024 042.pdf``). These
   should all be accepted.
2. **False negative** — a hallucinated response that was
   being accepted because the validation was too loose.
   The example: a response that invents a document number
   (``9999/999``) or a filename (``otro_doc.pdf``) that
   does not appear in the context. These must still be
   rejected.

We also pin the regex shape (filename requires a leading
alpha character so a doc number followed by ``.pdf`` is
not misclassified as a filename) and the normalisation
contract (commas and dots collapse to the same digit
string for amount comparison).
"""

from __future__ import annotations

import pytest

from app.ai.context import ContextItem
from app.ai.validation import (
    _AMOUNT_FALLBACK_PATTERN,
    _AMOUNT_PATTERN,
    _DOC_NUMBER_PATTERN,
    _normalise_amount,
    _normalise_doc_number,
    _normalise_filename,
    response_fabricates_documents,
)


# ---------------------------------------------------------------------------
# Normalisation primitives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1.234,56 EUR", "123456"),
        ("1234,56 EUR", "123456"),
        ("1,234.56", "123456"),
        ("5000.00", "500000"),
        ("5000", "5000"),
        ("EUR 241,00", "24100"),
        ("241,00 €", "24100"),
        ("15.000 EUR", "15000"),
        ("1.500.000,00", "150000000"),  # 1.5M EUR
        ("$1,234.56", "123456"),
    ],
)
def test_normalise_amount_handles_european_and_us_shapes(raw: str, expected: str) -> None:
    assert _normalise_amount(raw) == expected


@pytest.mark.parametrize(
    "raw, min_len",
    [
        ("0", 1),  # too short, returns None
        ("1", 1),
        ("12", 2),
        ("5000.00", 6),
    ],
)
def test_normalise_amount_length_floor(raw: str, min_len: int) -> None:
    """Sub-2-digit amounts return ``None`` so a stray ``"5"``
    or ``"1"`` mention does not poison the validation. Larger
    values must keep their full digit string.
    """
    result = _normalise_amount(raw)
    if len(raw.replace(".", "").replace(",", "")) < 2:
        assert result is None
    else:
        assert result is not None
        assert len(result) >= min_len


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("F-2026-044", "f2026044"),
        ("F 2026 044", "f2026044"),
        ("F2026/044", "f2026044"),
        ("F2026.044", "f2026044"),
        ("2026/143", "2026143"),
        ("2026-143", "2026143"),
        ("2026.143", "2026143"),
        ("442403", "442403"),
        ("F26-001", "f26001"),
    ],
)
def test_normalise_doc_number_handles_separators(raw: str, expected: str) -> None:
    assert _normalise_doc_number(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("presupuesto_2024_042.pdf", "presupuesto2024042.pdf"),
        ("presupuesto 2024 042.pdf", "presupuesto2024042.pdf"),
        ("presupuesto-2024-042.pdf", "presupuesto2024042.pdf"),
        ("UPPER_case.PDF", "uppercase.pdf"),
    ],
)
def test_normalise_filename_handles_internal_separators(raw: str, expected: str) -> None:
    """A filename with internal spaces, dashes, or
    underscores in the middle of the stem should collapse to
    a single canonical form so a context that lists the file
    with ``_`` and an answer that quotes it with spaces match.

    Note: the dots between digit groups are preserved
    (``.2024.042.pdf`` stays as ``presupuesto.2024.042.pdf``)
    so the matching step can still separate the stem from
    the extension.
    """
    assert _normalise_filename(raw) == expected


# ---------------------------------------------------------------------------
# False positives (should be accepted)
# ---------------------------------------------------------------------------


def _budget_context() -> list[ContextItem]:
    """Standard context used by the false-positive tests:
    one budget document with a known amount and a filename
    that mixes underscores and digits.
    """
    return [
        ContextItem(
            title="Presupuesto 2024/042",
            summary="presupuesto: numero 2024/042 cliente HOTEL total 5000.00 EUR",
            excerpt="importe total 5000.00 EUR",
            document_id=1,
            document_filename="presupuesto_2024_042.pdf",
            page_number=1,
        )
    ]


def test_response_with_european_amount_format_is_accepted() -> None:
    """The context has ``5000.00 EUR`` and the answer re-states
    it as ``5.000,00 EUR`` (European). Both must normalise to
    the same digit string and the response must be accepted.
    """
    answer = "El presupuesto 2024/042 es por 5.000,00 EUR."
    assert response_fabricates_documents(answer, _budget_context()) is False


def test_response_with_us_amount_format_is_accepted() -> None:
    """Same context, but the answer re-states the amount as
    ``5,000.00 EUR`` (US-style). Both should normalise to the
    same digit string and the response must be accepted.
    """
    answer = "Total: 5,000.00 EUR."
    assert response_fabricates_documents(answer, _budget_context()) is False


def test_response_with_filename_internal_spaces_is_accepted() -> None:
    """The context lists the file as ``presupuesto_2024_042.pdf``
    and the answer quotes it as ``presupuesto 2024 042.pdf``
    (with spaces). The filename normaliser should treat both
    as the same document, so the response must be accepted.
    """
    answer = 'Mira el archivo "presupuesto 2024 042.pdf".'
    assert response_fabricates_documents(answer, _budget_context()) is False


def test_response_with_filename_dashes_is_accepted() -> None:
    """Same context, answer quotes the file with dashes. The
    filename normaliser treats ``-`` as a separator, so both
    collapse to the same key.
    """
    answer = 'El archivo es "presupuesto-2024-042.pdf".'
    assert response_fabricates_documents(answer, _budget_context()) is False


# ---------------------------------------------------------------------------
# False negatives (should be rejected)
# ---------------------------------------------------------------------------


def test_hallucinated_document_number_is_rejected() -> None:
    """A document number that does not appear in the context is
    a hallucination. The earlier regex was too narrow and
    missed prefixed numbers; the new one catches both the
    ``9999/999`` family and the ``F-2026-044`` family.
    """
    answer = "El presupuesto 9999/999 es por 15000 EUR."
    assert response_fabricates_documents(answer, _budget_context()) is True


def test_hallucinated_filename_is_rejected() -> None:
    r"""A filename that is not in the context is a hallucination.
    The earlier filename regex was too narrow (``\w`` only,
    no spaces) so a hallucination with a space slipped
    through; the new regex matches filename-shaped strings
    with internal spaces and the normalisation step rejects
    anything not in the known set.
    """
    answer = "Mira el archivo otro_doc.pdf."
    assert response_fabricates_documents(answer, _budget_context()) is True


def test_hallucinated_amount_is_rejected() -> None:
    """An amount that does not appear in the context is a
    hallucination. ``999,99 EUR`` does not match the context's
    ``5000.00 EUR`` (normalised: ``99999`` vs ``500000``),
    so the response must be rejected.
    """
    answer = "El total es 999,99 EUR."
    assert response_fabricates_documents(answer, _budget_context()) is True


def test_hallucinated_prose_without_numbers_is_still_accepted() -> None:
    """A response that invents no concrete reference (no
    filename, no document number, no amount) does not trip
    the heuristic. The gate is **permissive on prose** and
    only fires on the specific tokens it knows about. This
    is intentional: blocking on prose would kill the
    conversational tone of the answer.
    """
    answer = (
        "Hemos revisado toda la documentacion disponible y la conclusion es que falta informacion."
    )
    assert response_fabricates_documents(answer, _budget_context()) is False


# ---------------------------------------------------------------------------
# Regex shape regressions
# ---------------------------------------------------------------------------


def test_filename_regex_requires_leading_alpha() -> None:
    """A bare number followed by an extension (e.g. ``042.pdf``
    in a doc-number context) must NOT be matched as a
    filename. The regex requires a leading alphabetic
    character so doc numbers and stray ``.pdf`` substrings
    do not trigger the filename check.
    """
    pat = r"\b[A-Za-z][\w./\- ]{2,}\.(?:pdf|msg|docx|doc|xlsx|png|jpe?g|tiff?)\b"
    import re

    # The stem must start with a non-digit alpha. ``042.pdf``
    # alone is a doc number, not a filename, so the regex
    # must skip it.
    assert (
        re.findall(pat, "doc 042.pdf, page 1", flags=re.IGNORECASE) == ["doc 042.pdf"]
        or re.findall(pat, "doc 042.pdf, page 1", flags=re.IGNORECASE) == []
    )
    # The intent: ``042.pdf`` by itself is not a filename; the
    # regex MUST require a leading alpha.
    assert re.search(pat, "042.pdf", flags=re.IGNORECASE) is None
    # But ``presupuesto 2024 042.pdf`` IS a filename.
    assert re.findall(pat, "presupuesto 2024 042.pdf", flags=re.IGNORECASE) == [
        "presupuesto 2024 042.pdf"
    ]


def test_doc_number_regex_still_matches_prefixed_numbers() -> None:
    """The earlier regex only matched the bare ``1234/567``
    or ``1234-567`` shapes; a hallucinated ``F-2026-044``
    used to slip through. The current regex still matches
    the prefixed case.
    """
    assert _DOC_NUMBER_PATTERN.search("F-2026-044")
    assert _DOC_NUMBER_PATTERN.search("2026/143")
    assert _DOC_NUMBER_PATTERN.search("442403")


def test_amount_patterns_catch_bare_decimal() -> None:
    """The strict pattern requires a thousands block; a bare
    decimal like ``5000.00`` does NOT match it (the integer
    part is 4 digits, not 1-3). The fallback pattern fills
    the gap. The combined ``_extract_known_amounts`` uses
    both, so a context with ``5000.00`` is correctly
    populated.
    """
    assert _AMOUNT_PATTERN.search("5000.00") is None
    assert _AMOUNT_FALLBACK_PATTERN.search("5000.00") is not None
    assert _AMOUNT_PATTERN.search("1.500,00") is not None
    assert _AMOUNT_FALLBACK_PATTERN.search("1.500,00") is not None
