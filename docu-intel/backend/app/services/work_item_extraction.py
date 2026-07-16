"""PM4.3 — Extraction of construction work items and measurements.

Parses tables from mediciones/presupuestos documents and extracts
structured work items with code, description, unit, quantity, price.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("app.services.work_item_extraction")


@dataclass
class ExtractedWorkChapter:
    """A chapter in a construction budget/measurements."""
    code: str
    title: str
    order_index: int = 0
    parent_code: str | None = None


@dataclass
class ExtractedWorkItem:
    """A work item (partida) from mediciones/presupuesto."""
    code: str
    description: str
    unit: str
    quantity: float | None = None
    unit_price: float | None = None
    total_price: float | None = None
    zone: str | None = None
    floor: str | None = None
    room: str | None = None
    chapter_code: str | None = None
    confidence: float = 0.0
    source_text: str = ""


@dataclass
class ExtractedBreakdown:
    """Measurement breakdown for a work item."""
    work_item_code: str
    length_m: float | None = None
    width_m: float | None = None
    height_m: float | None = None
    units: int | None = None
    formula: str | None = None
    computed_quantity: float | None = None
    description: str | None = None


# Patterns for table detection
_TABLE_HEADER_RE = re.compile(
    r"(?:concepto|partida|descripcion|descripción|article|item).*?"
    r"(?:unidad|unit|ud).*?"
    r"(?:cantidad|quantity|qty|medida)",
    re.IGNORECASE,
)
_CODE_RE = re.compile(r"^(\d+(?:[.:]\d+)*)\s+(.+)")
_UNIT_RE = re.compile(r"\b(m2|m3|ml|kg|ud|un|bols|lote|global|juego|par|set)\b", re.IGNORECASE)
# Avoid the trailing ``2``/``3`` in units such as ``m2`` and ``m3``.  Those
# digits previously became the first numeric value, shifting quantity, unit
# price and total one column to the left.
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])(\d+(?:[.,]\d+)*)")
_PRICE_RE = re.compile(r"(\d+(?:[.,]\d{2,})+)")


def extract_work_items_from_text(
    text: str,
    document_id: int | None = None,
    page_number: int | None = None,
) -> tuple[list[ExtractedWorkChapter], list[ExtractedWorkItem], list[ExtractedBreakdown]]:
    """Extract work items and chapters from text (OCR output or PDF text).

    Returns tuple of (chapters, items, breakdowns).
    """
    chapters: list[ExtractedWorkChapter] = []
    items: list[ExtractedWorkItem] = []
    breakdowns: list[ExtractedBreakdown] = []

    lines = text.split("\n")
    current_chapter: ExtractedWorkChapter | None = None
    chapter_order = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Try to match chapter heading (e.g. "1 OBJETOS", "2.1 PREPARACIÓN DEL TERRENO")
        chapter_match = _CODE_RE.match(line)
        if chapter_match:
            code = chapter_match.group(1)
            title = chapter_match.group(2).strip()

            # Determine if this is a chapter or an item
            has_unit = _UNIT_RE.search(line)
            has_price = _PRICE_RE.search(line)

            if not has_unit and not has_price:
                # Likely a chapter
                current_chapter = ExtractedWorkChapter(
                    code=code,
                    title=title,
                    order_index=chapter_order,
                    parent_code=_get_parent_code(code),
                )
                chapters.append(current_chapter)
                chapter_order += 1
                continue

        # Try to match work item line
        item = _parse_work_item_line(line, current_chapter)
        if item:
            items.append(item)

    # Compute breakdown quantities
    for bd in breakdowns:
        if bd.length_m and bd.width_m:
            bd.computed_quantity = bd.length_m * bd.width_m
            if bd.units:
                bd.computed_quantity *= bd.units

    return chapters, items, breakdowns


def _parse_work_item_line(
    line: str,
    current_chapter: ExtractedWorkChapter | None,
) -> ExtractedWorkItem | None:
    """Parse a single line as a work item."""
    # Look for code + description pattern
    match = _CODE_RE.match(line)
    if not match:
        return None

    code = match.group(1)
    rest = match.group(2)

    # Extract unit
    unit_match = _UNIT_RE.search(rest)
    unit = unit_match.group(1).lower() if unit_match else "ud"

    # Extract numbers that could be quantity, unit_price, total_price
    number_matches = list(_NUMBER_RE.finditer(rest))
    numbers = [_parse_number(match.group(1)) for match in number_matches]
    numbers = [value for value in numbers if value is not None]

    quantity = numbers[0] if len(numbers) >= 1 else None
    unit_price = numbers[1] if len(numbers) >= 2 else None
    total_price = numbers[2] if len(numbers) >= 3 else None

    # Description is the text between code and first number
    desc_end = number_matches[0].start() if number_matches else len(rest)
    description = rest[:desc_end].strip() if desc_end > 0 else rest.strip()
    # Remove unit from description
    if unit_match:
        description = description.replace(unit_match.group(0), "").strip()

    if not description:
        return None

    return ExtractedWorkItem(
        code=code,
        description=description,
        unit=unit,
        quantity=quantity,
        unit_price=unit_price,
        total_price=total_price,
        chapter_code=current_chapter.code if current_chapter else None,
        confidence=0.7 if quantity else 0.5,
        source_text=line[:300],
    )


def _parse_number(value: str) -> float | None:
    """Parse common Spanish/English monetary values deterministically."""
    raw = (value or "").strip()
    if not raw:
        return None
    if "," in raw and "." in raw:
        # The right-most separator is the decimal mark.
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _get_parent_code(code: str) -> str | None:
    """Get parent chapter code (e.g. '2.1' -> '2')."""
    parts = code.rsplit(".", 1)
    return parts[0] if len(parts) > 1 else None


def aggregate_work_items(items: list[ExtractedWorkItem]) -> dict:
    """Aggregate work items by chapter, zone, or unit for summary."""
    result = {
        "total_items": len(items),
        "total_quantity": 0.0,
        "total_price": 0.0,
        "by_chapter": {},
        "by_unit": {},
        "by_zone": {},
    }

    for item in items:
        if item.quantity:
            result["total_quantity"] += item.quantity
        if item.total_price:
            result["total_price"] += float(item.total_price)

        # By chapter
        ch = item.chapter_code or "unknown"
        if ch not in result["by_chapter"]:
            result["by_chapter"][ch] = {"count": 0, "quantity": 0.0, "price": 0.0}
        result["by_chapter"][ch]["count"] += 1
        if item.quantity:
            result["by_chapter"][ch]["quantity"] += item.quantity
        if item.total_price:
            result["by_chapter"][ch]["price"] += float(item.total_price)

        # By unit
        u = item.unit
        if u not in result["by_unit"]:
            result["by_unit"][u] = {"count": 0, "quantity": 0.0}
        result["by_unit"][u]["count"] += 1
        if item.quantity:
            result["by_unit"][u]["quantity"] += item.quantity

        # By zone
        z = item.zone or item.room or "general"
        if z not in result["by_zone"]:
            result["by_zone"][z] = {"count": 0, "quantity": 0.0, "price": 0.0}
        result["by_zone"][z]["count"] += 1
        if item.quantity:
            result["by_zone"][z]["quantity"] += item.quantity
        if item.total_price:
            result["by_zone"][z]["price"] += float(item.total_price)

    return result


__all__ = [
    "ExtractedWorkChapter",
    "ExtractedWorkItem",
    "ExtractedBreakdown",
    "extract_work_items_from_text",
    "aggregate_work_items",
]
