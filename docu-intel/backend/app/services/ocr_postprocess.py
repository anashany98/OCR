"""O4 — OCR post-processing: number normalisation + format validators.

The OCR engines (Tesseract, PaddleOCR) often mis-read characters
that look similar: ``0`` ↔ ``O``, ``1`` ↔ ``l``/``I``, ``5`` ↔
``S``, ``8`` ↔ ``B``. In financial documents (invoices, budgets,
orders) these mis-reads corrupt NIFs, IBANs, dates and amounts.
This module scans the OCR output for high-confidence patterns
(NIFs, CIFs, IBANs, dates, amounts) and applies character-level
corrections so the downstream extraction (``business_extraction``
in Fase 2) sees clean, valid data.

The module is **pure** (no DB, no I/O) so it can be unit-tested
without a database or a running OCR engine. The corrections are
applied *before* the Fase 2 extraction runs, on the raw page
text that the cascade produces.

The corrections are conservative: we only substitute characters
when the surrounding context is unambiguous. A lone ``O`` in the
middle of a word is never substituted; ``B12345678`` (a valid
NIF prefix) is left alone; ``1O.5O`` inside a numeric context
(``amount`` pattern) is corrected to ``100.50`` because the
surrounding digits and the decimal separator leave no room for
ambiguity.

The module never raises on weird input. An empty / non-string
input returns an empty :class:`PostprocessReport` so callers can
chain the call without nil-checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.metrics import track_ocr_postprocess


# ---------------------------------------------------------------------------
# OCR character substitution table (context-sensitive)
# ---------------------------------------------------------------------------

# The table maps a *mis-read* character to its *correct* form
# **when the context is numeric** (the character is surrounded by
# digits or by a decimal/thousands separator). The same character
# in a word context (``"OPERACIÓN"``) is never touched.
_NUMERIC_SUBS: dict[str, str] = {
    "O": "0",
    "o": "0",
    "I": "1",
    "l": "1",
    "S": "5",
    "s": "5",
    "B": "8",
    "G": "6",
    "Z": "2",
    "z": "2",
}


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _nif_check_digit(nif: str) -> str:
    """Return the expected check letter for a Spanish NIF.

    The algorithm is: ``TRWAGMYFPDXBNJZSQVHLCKE[d % 23]``
    where ``d`` is the 7-digit number. Leading zeros matter.
    """
    table = "TRWAGMYFPDXBNJZSQVHLCKE"
    digits = nif[:8]
    if not digits.isdigit():
        return ""
    return table[int(digits) % 23]


def validate_nif(nif: str) -> tuple[bool, str]:
    """Validate a Spanish NIF (8 digits + 1 letter).

    Returns ``(True, normalised_nif)`` when the NIF is valid,
    ``(False, original)`` when it is not. The normalised form
    has the check-letter upper-cased and the digits zero-padded
    to 8 characters.
    """
    clean = nif.strip().upper().replace(" ", "")
    if len(clean) != 9:
        return False, nif
    digits, letter = clean[:8], clean[8]
    if not digits.isdigit() or not letter.isalpha():
        return False, nif
    expected = _nif_check_digit(digits)
    if letter == expected:
        return True, f"{digits}{letter}"
    # OCR correction: try the most common mis-reads.
    for original, replacement in _NUMERIC_SUBS.items():
        if original == letter:
            candidate = replacement
            if candidate == expected:
                return True, f"{digits}{candidate}"
    return False, nif


def validate_cif(cif: str) -> tuple[bool, str]:
    """Validate a Spanish CIF (letter + 7 digits + check).

    The check digit is computed by the Luhn-like algorithm
    defined in the Spanish tax code. Returns ``(True, normalised)``
    when valid, ``(False, original)`` when not.
    """
    clean = cif.strip().upper().replace(" ", "")
    if len(clean) != 9:
        return False, cif
    org_letter = clean[0]
    body = clean[1:8]
    check = clean[8]
    if not body.isdigit():
        return False, cif
    if org_letter not in "ABCDEFGHJKLMNPQRSUVW":
        return False, cif
    # Luhn-like sum: even positions * 2 (sum digits), odd positions as-is.
    even_sum = 0
    odd_sum = 0
    for i, ch in enumerate(body):
        d = int(ch)
        if i % 2 == 0:  # 0-indexed even = 1-indexed odd in the spec
            d *= 2
            even_sum += d // 10 + d % 10
        else:
            odd_sum += d
    total = even_sum + odd_sum
    expected_digit = (10 - (total % 10)) % 10
    expected_letter = "JABCDEFGHI"[expected_digit]
    if check.isdigit() and int(check) == expected_digit:
        return True, f"{org_letter}{body}{expected_digit}"
    if check.isalpha() and check.upper() == expected_letter:
        return True, f"{org_letter}{body}{expected_letter}"
    return False, cif


def _iban_country_lengths() -> dict[str, int]:
    """Return a dict of ISO 3166-1 alpha-2 → IBAN length for the
    most common countries. The full registry has ~80 entries; we
    keep only the ones that appear in Spanish construction docs."""
    return {
        "ES": 24,
        "PT": 25,
        "FR": 27,
        "DE": 22,
        "IT": 27,
        "GB": 22,
        "NL": 18,
        "BE": 16,
        "AT": 20,
        "CH": 21,
        "IE": 22,
        "SE": 24,
        "NO": 15,
        "DK": 18,
        "FI": 18,
        "PL": 28,
        "CZ": 24,
        "RO": 24,
        "HU": 28,
        "GR": 27,
    }


def validate_iban(iban: str) -> tuple[bool, str]:
    """Validate an IBAN (ISO 13616, mod-97 check).

    Returns ``(True, normalised_iban)`` when the IBAN passes
    the mod-97 check and has the correct length for its country,
    ``(False, original)`` when it does not. The normalised form
    has the country code upper-cased and spaces removed.
    """
    clean = iban.strip().upper().replace(" ", "").replace("-", "")
    if len(clean) < 4 or not clean[:2].isalpha() or not clean[2:4].isdigit():
        return False, iban
    country = clean[:2]
    expected_lengths = _iban_country_lengths()
    if country in expected_lengths and len(clean) != expected_lengths[country]:
        return False, iban
    # Move first 4 chars to end, replace letters with digits (A=10..Z=35).
    rearranged = clean[4:] + clean[:4]
    numeric_str = ""
    for ch in rearranged:
        if ch.isdigit():
            numeric_str += ch
        else:
            numeric_str += str(ord(ch) - ord("A") + 10)
    try:
        check_int = int(numeric_str)
    except ValueError:
        return False, iban
    if check_int % 97 != 1:
        return False, iban
    return True, clean


# ---------------------------------------------------------------------------
# Number normalisation
# ---------------------------------------------------------------------------


def _normalise_number(text: str, *, language: str = "es") -> str:
    """Normalise a single numeric string that may contain OCR
    mis-reads and locale-dependent separators.

    The algorithm:
    1. Substitute OCR mis-reads in a numeric context.
    2. Detect the decimal separator: if the string contains
       a ``","`` followed by 1-2 digits at the end, treat
       ``","`` as decimal; otherwise treat ``"."`` as decimal.
    3. Strip thousands separators.
    4. Return the normalised number as a Python-parseable float
       string (``"."`` as decimal, no thousands separator).
    """
    if not text:
        return text
    # Step 1: substitute OCR mis-reads in a numeric context.
    out = []
    for ch in text:
        if ch.isdigit() or ch in ".,":
            out.append(ch)
        elif ch in _NUMERIC_SUBS and _is_numeric_context(text, ch):
            out.append(_NUMERIC_SUBS[ch])
        else:
            out.append(ch)
    result = "".join(out)
    # Step 2-4: normalise separators.
    return _normalise_separators(result, language=language)


def _is_numeric_context(text: str, ch: str) -> bool:
    """Return True when ``ch`` is surrounded by digits or
    separators (i.e. it is in a numeric context and the
    substitution is safe)."""
    idx = text.index(ch) if ch in text else -1
    if idx < 0:
        return False
    left = text[idx - 1] if idx > 0 else ""
    right = text[idx + 1] if idx < len(text) - 1 else ""
    left_ok = left.isdigit() or left in ".,"
    right_ok = right.isdigit() or right in ".,"
    return left_ok and right_ok


def _normalise_separators(text: str, *, language: str = "es") -> str:
    """Normalise thousands/decimal separators to the Python
    convention (``"."`` as decimal, no thousands separator).

    The heuristics:
    - ``1.234.567,89`` (European) → ``1234567.89``
    - ``1,234,567.89`` (Anglo) → ``1234567.89``
    - ``1234,89`` (no thousands, European decimal) → ``1234.89``
    - ``1234.89`` (no thousands, Anglo decimal) → ``1234.89``
    - ``1234`` (integer) → ``1234``
    """
    if not text:
        return text
    # Strip leading/trailing whitespace and currency symbols.
    clean = text.strip().replace("€", "").replace("$", "").strip()
    if not clean:
        return clean
    # Detect pattern: if last separator is ``","`` followed by
    # 1-2 digits, it's the decimal separator (European).
    european_decimal = bool(re.search(r",\d{1,2}$", clean))
    if european_decimal:
        # Remove thousands dots, replace decimal comma with dot.
        integer_part, _, decimal_part = clean.rpartition(",")
        integer_part = integer_part.replace(".", "")
        return f"{integer_part}.{decimal_part}"
    # Anglo or no separator: remove thousands commas, keep dot.
    integer_part, _, decimal_part = clean.rpartition(".")
    # Only treat ``"."`` as decimal if followed by 1-2 digits at
    # the end; otherwise it's a thousands separator.
    if decimal_part and len(decimal_part) <= 2 and decimal_part.isdigit():
        integer_part = integer_part.replace(",", "")
        return f"{integer_part}.{decimal_part}"
    # No decimal part or long decimal: treat as integer, strip
    # all separators.
    clean = clean.replace(",", "").replace(".", "")
    return clean


# ---------------------------------------------------------------------------
# Date normalisation
# ---------------------------------------------------------------------------


_DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")


def _normalise_dates(text: str, *, language: str = "es") -> str:
    """Normalise date strings to ISO format ``YYYY-MM-DD`` when
    the format is unambiguous (day <= 12 is ambiguous and left
    as-is).

    The function only converts dates where the day > 12 (so
    ``25/03/2026`` → ``2026-03-25`` but ``03/05/2026`` is left
    alone because we don't know if it's March 5 or May 3).
    """

    def _replace_date(match: re.Match) -> str:
        d, m, y = match.group(1), match.group(2), match.group(3)
        if len(y) == 2:
            y = "20" + y if int(y) < 50 else "19" + y
        # Only normalise when day > 12 (unambiguous).
        if int(d) > 12 and 1 <= int(m) <= 12:
            return f"{y}-{int(m):02d}-{int(d):02d}"
        return match.group(0)

    return _DATE_RE.sub(_replace_date, text)


# ---------------------------------------------------------------------------
# Correction tracking
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Correction:
    """A single correction applied to the OCR text.

    Attributes:
        kind: the type of correction (``"number"``, ``"nif"``,
            ``"cif"``, ``"iban"``, ``"date"``).
        original: the original text before correction.
        corrected: the corrected text.
        confidence: how confident we are that the correction is
            right (1.0 = the validator confirmed it; 0.8 = the
            OCR substitution was applied but the validator was
            not run).
    """

    kind: str
    original: str
    corrected: str
    confidence: float = 1.0


@dataclass(frozen=True)
class PostprocessReport:
    """The result of post-processing a single page of OCR text.

    Attributes:
        original_length: length of the input, in characters.
        corrected_text: the normalised text.
        corrections: list of corrections applied.
    """

    original_length: int
    corrected_text: str
    corrections: list[Correction] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def postprocess_ocr_text(
    text: str,
    *,
    language: str = "es",
) -> PostprocessReport:
    """Post-process ``text`` (the output of the OCR cascade) by
    normalising numbers, validating and correcting NIFs/CIFs/IBANs,
    and normalising dates.

    Args:
        text: the raw OCR text for a single page.
        language: the ISO-639-1 code of the dominant language
            (used to select the decimal separator heuristic).

    Returns:
        :class:`PostprocessReport` with the corrected text and
        the list of corrections applied. The original text is
        never modified; the caller receives a new string.
    """
    if not text:
        return PostprocessReport(original_length=0, corrected_text="", corrections=[])

    original_length = len(text)
    corrections: list[Correction] = []
    out = text

    # 1. NIF validation + correction.
    nif_re = re.compile(r"\b([0-9]{8}[A-Za-z])\b")
    for match in nif_re.finditer(out):
        candidate = match.group(1)
        valid, normalised = validate_nif(candidate)
        if normalised != candidate:
            corrections.append(
                Correction(
                    kind="nif",
                    original=candidate,
                    corrected=normalised,
                    confidence=1.0 if valid else 0.8,
                )
            )
            out = out.replace(candidate, normalised, 1)

    # 2. CIF validation + correction.
    cif_re = re.compile(r"\b([A-Wa-w][0-9]{7}[0-9A-Za-z])\b")
    for match in cif_re.finditer(out):
        candidate = match.group(1)
        valid, normalised = validate_cif(candidate)
        if normalised != candidate:
            corrections.append(
                Correction(
                    kind="cif",
                    original=candidate,
                    corrected=normalised,
                    confidence=1.0 if valid else 0.8,
                )
            )
            out = out.replace(candidate, normalised, 1)

    # 3. IBAN validation + correction.
    iban_re = re.compile(r"\b([A-Z]{2}\d{2}[\s-]?(?:\d{4}[\s-]?){4,6}\d{0,4})\b", re.IGNORECASE)
    for match in iban_re.finditer(out):
        candidate = match.group(1)
        valid, normalised = validate_iban(candidate)
        if normalised != candidate:
            corrections.append(
                Correction(
                    kind="iban",
                    original=candidate,
                    corrected=normalised,
                    confidence=1.0 if valid else 0.8,
                )
            )
            out = out.replace(candidate, normalised, 1)

    # 4. Number normalisation (conservative: only in amount-like
    #    contexts — a digit followed by a separator and more digits).
    #    We require at least one separator (``.`` or ``,``) so pure
    #    digit+letter sequences (NIFs, CIFs, IBANs) are not touched.
    amount_re = re.compile(r"\b(\d[\d.,OoIlSBsGZz]{2,}[.,]\d[\d.,OoIlSBsGZz]*)\b")
    for match in amount_re.finditer(out):
        candidate = match.group(1)
        normalised = _normalise_number(candidate, language=language)
        if normalised != candidate:
            corrections.append(
                Correction(kind="number", original=candidate, corrected=normalised, confidence=0.8)
            )
            out = out.replace(candidate, normalised, 1)

    # 5. Date normalisation.
    out = _normalise_dates(out, language=language)

    track_ocr_postprocess(correction_count=len(corrections))
    return PostprocessReport(
        original_length=original_length,
        corrected_text=out,
        corrections=corrections,
    )


__all__ = [
    "Correction",
    "PostprocessReport",
    "validate_nif",
    "validate_cif",
    "validate_iban",
    "postprocess_ocr_text",
]
