"""Layout-aware line extraction from OCR/PDF blocks.

The legacy :func:`app.services.business_extraction._extract_lines` is
100% regex on plain text and requires the line to fit the pattern
``REF DESC QTY UNIT UNIT_PRICE TOTAL`` on a single line. Real invoices
frequently break that pattern:

* The description wraps to a second line.
* Columns are not left-aligned (PaddleOCR column detection drifts).
* The unit is sometimes a unit price suffix ("€/ud").
* The reference and the description are merged when OCR eats the gap.

This module works on the per-line OCR blocks (each block = one OCR
line with a bounding box) and clusters them by **Y** (rows) and **X**
(columns) within each page. It then matches the first row whose tokens
look like a header to a known column dictionary, and assigns every
data row to those columns.

The output is the same :class:`app.services.business_extraction.ExtractedLine`
dataclass, so callers do not need to change.

If any step fails (no header detected, fewer than 2 columns, fewer than
2 data rows) the function falls back to the regex on plain text so
the legacy behaviour is preserved.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable

from app.parsers.types import ExtractedBlock, ExtractedPage
from app.services.business_extraction import ExtractedLine, _extract_lines, _parse_amount

# Header keywords per column. Matched case-insensitively as whole words
# against the first-row tokens. Order matters: when a token matches
# more than one field, the first match wins. ``unit_price`` and
# ``unit`` are checked BEFORE ``quantity`` so the substring "ud" inside
# "precio ud" is not misclassified as a quantity column.
_HEADER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "reference": ("ref", "referencia", "código", "codigo", "art", "artículo", "articulo"),
    "description": ("descripción", "descripcion", "concepto", "detalle"),
    "unit_price": (
        "precio ud",
        "precio unit",
        "p.unit",
        "p.unitario",
        "precio",
        "importe ud",
        "tarifa",
    ),
    "unit": ("unidad", "uni"),
    "quantity": ("cant", "cantidad", "uds", "unidades", "qty"),
    "total_price": ("total", "importe", "subtotal", "importe total", "total línea", "total linea"),
}

# Fallback aliases when the first row does not contain enough tokens
# to map every column. Useful for compact 4-column tables.
_FALLBACK_HEADER: dict[int, str] = {
    # 3 cols: ref, desc, total
    3: {"col0": "reference", "col1": "description", "col2": "total_price"},
    # 4 cols: ref, desc, qty, total  OR  ref, desc, unit_price, total
    4: {"col0": "reference", "col1": "description", "col2": "quantity", "col3": "total_price"},
    # 5 cols: ref, desc, qty, unit_price, total
    5: {
        "col0": "reference",
        "col1": "description",
        "col2": "quantity",
        "col3": "unit_price",
        "col4": "total_price",
    },
    # 6 cols: ref, desc, qty, unit, unit_price, total
    6: {
        "col0": "reference",
        "col1": "description",
        "col2": "quantity",
        "col3": "unit",
        "col4": "unit_price",
        "col5": "total_price",
    },
}

# Minimum requirements for a row to be considered a data row.
_MIN_ROW_TOKENS = 2
_MIN_DATA_ROWS = 1


def _block_center(block: ExtractedBlock) -> tuple[float, float]:
    """Return (x_center, y_center) for a block. Falls back to (0, 0)."""
    if not block.bbox:
        return (0.0, 0.0)
    x1, y1, x2, y2 = block.bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _block_x_range(block: ExtractedBlock) -> tuple[float, float]:
    if not block.bbox:
        return (0.0, 0.0)
    return (block.bbox[0], block.bbox[2])


def _row_tolerance(page_height: float | None) -> float:
    """Y tolerance to consider two blocks the same row. Scales with page
    height so a 6-page A3 plan and a 1-page business card behave the
    same. Default 1/40 of the page height, floor 6 px."""
    if not page_height or page_height <= 0:
        return 6.0
    return max(6.0, page_height / 40.0)


def _cluster_rows(blocks: list[ExtractedBlock], tolerance: float) -> list[list[ExtractedBlock]]:
    """Sort blocks by Y, then group by Y-proximity."""
    ordered = sorted(blocks, key=lambda b: _block_center(b)[1])
    rows: list[list[ExtractedBlock]] = []
    for block in ordered:
        cy = _block_center(block)[1]
        if (
            rows
            and abs(cy - statistics.median(_block_center(b)[1] for b in rows[-1])) <= tolerance
            or rows
            and abs(cy - _block_center(rows[-1][-1])[1]) <= tolerance
        ):
            rows[-1].append(block)
        else:
            rows.append([block])
    # Sort each row by X for stable column assignment.
    return [sorted(r, key=_block_center) for r in rows]


def _match_header_token(text: str) -> str | None:
    """Return the semantic field for a header cell, or None if no match.

    Multi-word keywords (e.g. ``"precio ud"``) are tried BEFORE
    single-word keywords so the substring "ud" inside "PRECIO UD" is
    not misclassified as a quantity column.
    """
    normalised = text.strip().lower()
    # Drop trailing punctuation that OCR adds ("ref.").
    normalised = normalised.rstrip(":.-")
    # Two passes: first multi-word, then single-word. This avoids
    # "PRECIO UD" matching "ud" before "precio ud" gets a chance.
    flat = [(f, k) for f, ks in _HEADER_KEYWORDS.items() for k in ks]
    multi = [(f, k) for f, k in flat if " " in k]
    single = [(f, k) for f, k in flat if " " not in k]
    for field, kw in multi:
        if re.search(rf"\b{re.escape(kw)}\b", normalised):
            return field
    for field, kw in single:
        if re.search(rf"\b{re.escape(kw)}\b", normalised):
            return field
    return None


def _detect_header(row: list[ExtractedBlock]) -> dict[int, str] | None:
    """Map column index -> field for the first row whose tokens look
    like a header. Returns None if no header is detected.

    Strategy:
    * At least 2 of the first row's tokens must match a known keyword.
    * If the row matches some but not all, the unmatched columns are
      filled in from :data:`_FALLBACK_HEADER` based on the row's column
      count. This handles compact tables whose header is a single word
      like "DESCRIPCIÓN" + amounts.
    """
    matches: dict[int, str] = {}
    for idx, block in enumerate(row):
        field = _match_header_token(block.text or "")
        if field:
            matches[idx] = field
    if len(matches) < 2:
        return None
    ncols = len(row)
    if len(matches) < ncols:
        fallback = _FALLBACK_HEADER.get(ncols)
        if fallback:
            for col_key, field in fallback.items():
                idx = int(col_key[3:])
                if idx not in matches:
                    matches[idx] = field
    return matches if matches else None


def _classify_cell_value(text: str, field: str, locale: str) -> str | float | None:
    """Coerce a cell string to the right type for ``field``."""
    text = (text or "").strip()
    if not text:
        return None
    if field in {"quantity", "unit_price", "total_price"}:
        return _parse_amount(text, locale=locale)
    if field == "unit":
        return text
    return text


def _row_to_line(
    row: list[ExtractedBlock],
    column_fields: dict[int, str],
    column_x_centers: list[float],
    locale: str,
) -> ExtractedLine | None:
    """Build an :class:`ExtractedLine` from a data row.

    Assigns each block to the closest column by X center, then reads
    the field value with the right type coercion. Returns None when
    the row has too few useful cells (e.g. a single "TOTAL" footer).
    """
    if len(row) < _MIN_ROW_TOKENS:
        return None
    field_values: dict[str, object] = {
        "reference": None,
        "description": None,
        "quantity": None,
        "unit": None,
        "unit_price": None,
        "total_price": None,
    }
    confidences: list[float] = []
    for block in row:
        if not block.bbox:
            continue
        bcx = _block_center(block)[0]
        # Closest column by X center.
        col_idx = min(range(len(column_x_centers)), key=lambda i: abs(column_x_centers[i] - bcx))
        field = column_fields.get(col_idx)
        if not field:
            # Unmapped column → keep it as description so we do not
            # lose the text.
            field = "description"
        value = _classify_cell_value(block.text or "", field, locale)
        # Concatenate repeated description cells (wrapped lines).
        if field == "description" and field_values["description"]:
            field_values["description"] = f"{field_values['description']} {value}".strip()
        else:
            field_values[field] = value
        if block.confidence is not None:
            confidences.append(block.confidence)
    # A row that contributed nothing to description and total is
    # probably a separator or a footer — drop it.
    if not field_values.get("description") and not field_values.get("total_price"):
        return None
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.75
    return ExtractedLine(
        reference=field_values.get("reference")
        if isinstance(field_values.get("reference"), (str, type(None)))
        else None,
        description=field_values.get("description")
        if isinstance(field_values.get("description"), (str, type(None)))
        else None,
        quantity=field_values.get("quantity")
        if isinstance(field_values.get("quantity"), (int, float, type(None)))
        else None,
        unit=field_values.get("unit")
        if isinstance(field_values.get("unit"), (str, type(None)))
        else None,
        unit_price=field_values.get("unit_price")
        if isinstance(field_values.get("unit_price"), (int, float, type(None)))
        else None,
        total_price=field_values.get("total_price")
        if isinstance(field_values.get("total_price"), (int, float, type(None)))
        else None,
        confidence=round(min(0.95, max(0.40, avg_conf)), 2),
    )


def extract_lines_from_pages(
    pages: Iterable[ExtractedPage],
    *,
    locale: str = "es-ES",
) -> list[ExtractedLine]:
    """Extract line items from a list of pages using bbox clustering.

    Falls back to the legacy regex if clustering cannot find a header
    or if the page does not carry any bounding boxes.
    """
    all_lines: list[ExtractedLine] = []
    for page in pages:
        page_lines = _extract_lines_for_page(page, locale=locale)
        all_lines.extend(page_lines)
    if not all_lines:
        # Final fallback: legacy regex on the concatenated text.
        text = "\n".join(p.text for p in pages)
        return _extract_lines(text)
    return all_lines


def _extract_lines_for_page(page: ExtractedPage, *, locale: str) -> list[ExtractedLine]:
    blocks = [b for b in page.blocks if b.text and b.bbox]
    if len(blocks) < 2:
        return []
    tolerance = _row_tolerance(page.height)
    rows = _cluster_rows(blocks, tolerance)
    if len(rows) < 2:  # need at least header + 1 data row
        return []
    # Find the first row that looks like a header.
    header_idx = None
    column_fields: dict[int, str] | None = None
    column_x_centers: list[float] = []
    for idx, row in enumerate(rows):
        detected = _detect_header(row)
        if detected:
            header_idx = idx
            column_fields = detected
            column_x_centers = [_block_center(b)[0] for b in row]
            break
    if header_idx is None or column_fields is None:
        return []
    data_rows = rows[header_idx + 1 :]
    if len(data_rows) < _MIN_DATA_ROWS:
        return []
    lines: list[ExtractedLine] = []
    for row in data_rows:
        line = _row_to_line(row, column_fields, column_x_centers, locale=locale)
        if line is not None:
            lines.append(line)
    return lines


def extract_lines_from_text(text: str) -> list[ExtractedLine]:
    """Public alias of the legacy regex extractor.

    Kept as a stable entry point so callers can use
    :func:`app.services.extraction.extract_lines_from_text` regardless
    of whether they have layout info or not.
    """
    return _extract_lines(text)
