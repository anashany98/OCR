"""Shared date-parsing utilities.

Two callers historically had their own date handling:

* :mod:`app.services.business_extraction` (the ``_parse_date``
  function, numeric-only)
* :mod:`app.services.quality` (the ``_DATE_PATTERN`` regex, also
  numeric-only)

The :class:`datetime.date` constructor only accepts numeric input,
so the two callers had to fall back to a regex on the document text
to find a date. Both implementations used the same ``DD/MM/YYYY``
shape and ignored textual Spanish dates like
``"15 de junio de 2026"`` — a real supplier pattern that
business_extraction misses today.

This module centralises three concerns:

* :func:`find_dates_in_text` returns every plausible date in a blob
  (numeric + Spanish textual) so callers can flag or accept a
  document based on date evidence.
* :func:`parse_spanish_date` parses a single date string in either
  numeric or Spanish textual form.
* :func:`DATE_PATTERN` keeps the simple numeric regex used by
  :mod:`app.services.quality` for the *contains-a-date* check, so
  the constant has a single home.

The Spanish textual parser uses a fixed month map (no ``dateparser``
dependency) so the behaviour is deterministic and testable. If we
ever need multilingual support the function can be swapped for a
library call without touching the callers.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterable

# Numeric forms accepted by the parser. The first capture group is
# always the day, the second the month, the third the year (2 or
# 4 digits). Slash and dash are accepted; 2-digit years are
# mapped to 20YY.
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")

# "DD de MES de YYYY" / "DD de MES YYYY" / "DD MES YYYY" / "DD-MES-YYYY".
# ``MES`` is matched case-insensitively; trailing de is optional.
_TEXTUAL_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(?:de\s+)?([A-Za-záéíóúñ]+)(?:\s+de)?\s+(\d{2,4})\b",
    flags=re.IGNORECASE,
)

_SPANISH_MONTHS: dict[str, int] = {
    # Full names
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    # Common abbreviations
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}

# Re-export the simple "does this text contain any plausible numeric
# date" regex for the quality check. Kept here so callers do not
# need their own copy of the same pattern.
DATE_PATTERN: re.Pattern[str] = _NUMERIC_DATE_RE


def _coerce_year(raw: str) -> int | None:
    if not raw:
        return None
    try:
        year = int(raw)
    except ValueError:
        return None
    if year < 100:
        # 2-digit year: 30 → 2030, 95 → 1995. The cut-off is the
        # classic POSIX boundary (69 years ago = 1969, 70 years
        # ahead = 2070).
        year += 2000 if year < 70 else 1900
    return year


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_spanish_date(raw: str) -> date | None:
    """Parse a single Spanish date string.

    Accepts numeric forms (``"15/06/2026"``, ``"15-06-26"``) and
    textual forms (``"15 de junio de 2026"``, ``"15 jun 2026"``).
    Returns ``None`` for ambiguous or invalid input.
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None

    # Numeric first (cheap, high precision).
    numeric = _NUMERIC_DATE_RE.search(text)
    if numeric:
        day, month, year_raw = numeric.groups()
        year = _coerce_year(year_raw)
        if year is not None:
            try:
                day_i = int(day)
                month_i = int(month)
            except ValueError:
                return None
            if 1 <= month_i <= 12:
                return _safe_date(year, month_i, day_i)

    # Textual fallback. We accept both "15 de junio de 2026" and
    # the compact "15 jun 2026" by stripping the optional "de".
    textual = _TEXTUAL_DATE_RE.search(text)
    if textual:
        day_raw, month_raw, year_raw = textual.groups()
        month_norm = month_raw.lower().rstrip(".")
        month_num = _SPANISH_MONTHS.get(month_norm)
        year = _coerce_year(year_raw)
        if month_num is not None and year is not None:
            try:
                day_i = int(day_raw)
            except ValueError:
                return None
            return _safe_date(year, month_num, day_i)
    return None


def find_dates_in_text(text: str) -> list[date]:
    """Return every plausible date in ``text``, in document order.

    Numeric and Spanish textual dates are both recognised. Duplicates
    are preserved as found (callers can ``set(...)`` if they only
    care about uniqueness).
    """
    found: list[date] = []
    if not text:
        return found
    for match in _NUMERIC_DATE_RE.finditer(text):
        day_raw, month_raw, year_raw = match.groups()
        year = _coerce_year(year_raw)
        if year is None:
            continue
        try:
            day_i = int(day_raw)
            month_i = int(month_raw)
        except ValueError:
            continue
        if not 1 <= month_i <= 12:
            continue
        parsed = _safe_date(year, month_i, day_i)
        if parsed is not None:
            found.append(parsed)
    for match in _TEXTUAL_DATE_RE.finditer(text):
        day_raw, month_raw, year_raw = match.groups()
        month_num = _SPANISH_MONTHS.get(month_raw.lower().rstrip("."))
        year = _coerce_year(year_raw)
        if month_num is None or year is None:
            continue
        try:
            day_i = int(day_raw)
        except ValueError:
            continue
        parsed = _safe_date(year, month_num, day_i)
        if parsed is not None:
            found.append(parsed)
    return found


def first_date_in_text(text: str, *, preferred: Iterable[str] = ()) -> date | None:
    """Return the first plausible date in ``text``.

    ``preferred`` is an optional list of label substrings (case-
    insensitive). If any of them is found immediately followed by a
    date, that date is returned. Useful for "Fecha: 15/06/2026"
    patterns where the labelled date is more reliable than the
    first arbitrary numeric date in the body.
    """
    if not text:
        return None
    for label in preferred:
        pattern = re.compile(
            rf"{re.escape(label)}\s*[:#-]?\s*([^\n]+)",
            flags=re.IGNORECASE,
        )
        match = pattern.search(text)
        if match:
            parsed = parse_spanish_date(match.group(1))
            if parsed is not None:
                return parsed
    dates = find_dates_in_text(text)
    return dates[0] if dates else None
