"""O3 — Layout-aware text extraction for multi-column PDFs.

The default ``page.get_text("text")`` in PyMuPDF returns text in
*reading order* when the PDF is well-structured. But many
construction PDFs (invoices, measurement sheets, budgets) use
multi-column layouts where the reading order is wrong: the
emitter block on the left gets interleaved with the client block
on the right, and the line items in the middle get scrambled.

This module detects multi-column pages by looking at the
*distribution of text blocks across the page width*: if more
than 40% of the text blocks land in the right half of the page
AND there is a clear vertical gap in the middle, the page is
likely multi-column. When detected, the text is re-ordered by
reading the left column first, then the right column.

The module is **fail-safe**: on any error the original
``page.get_text("text")`` is returned unchanged.

The detection is **pure** (no ML, no GPU) and adds ~5ms per
page. The re-ordering is a simple sort on the x-coordinate of
each text block.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("app.services.layout_parser")


# Thresholds for multi-column detection.
_COLUMN_RATIO_THRESHOLD = 0.40  # ≥40% of blocks in the right half
_GAP_MIN_RATIO = 0.08  # vertical gap ≥8% of page width
_MIN_BLOCKS_FOR_DETECTION = 6  # need at least 6 blocks to detect


@dataclass(frozen=True)
class TextBlock:
    """A single text block extracted from a PDF page.

    Attributes:
        text: the text content.
        x0, y0, x1, y1: bounding box in PDF units (points).
        reading_order: the assigned reading order (0-indexed).
    """

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    reading_order: int = 0


@dataclass(frozen=True)
class LayoutResult:
    """The result of layout-aware text extraction.

    Attributes:
        text: the re-ordered text (or the original if no
            multi-column was detected).
        is_multicolumn: whether the multi-column heuristic
            fired.
        column_count: how many columns were detected (1 or 2).
        blocks: the individual text blocks with their reading
            order.
    """

    text: str
    is_multicolumn: bool
    column_count: int
    blocks: list[TextBlock]


def extract_layout_aware_text(page) -> LayoutResult:
    """Extract text from a PyMuPDF page with layout-aware
    reading order.

    Args:
        page: a ``fitz.Page`` object.

    Returns:
        :class:`LayoutResult` with the re-ordered text and
        metadata. On any error returns the original
        ``page.get_text("text")`` with ``is_multicolumn=False``.
    """
    try:
        raw_text = page.get_text("text").strip()
        if not raw_text:
            return LayoutResult(text="", is_multicolumn=False, column_count=1, blocks=[])

        # Extract text blocks with bounding boxes.
        blocks = _extract_blocks(page)
        if len(blocks) < _MIN_BLOCKS_FOR_DETECTION:
            return LayoutResult(text=raw_text, is_multicolumn=False, column_count=1, blocks=blocks)

        # Detect multi-column layout.
        is_multi, column_count, gap_x = _detect_multicolumn(page, blocks)
        if not is_multi:
            return LayoutResult(text=raw_text, is_multicolumn=False, column_count=1, blocks=blocks)

        # Re-order blocks by column then by y-position.
        reordered = _reorder_by_columns(blocks, gap_x)
        text = "\n".join(b.text for b in reordered if b.text.strip())
        return LayoutResult(
            text=text,
            is_multicolumn=True,
            column_count=column_count,
            blocks=reordered,
        )
    except Exception as exc:
        logger.debug("Layout parser failed: %s", exc)
        raw_text = page.get_text("text").strip()
        return LayoutResult(text=raw_text, is_multicolumn=False, column_count=1, blocks=[])


def _extract_blocks(page) -> list[TextBlock]:
    """Extract text blocks from a PyMuPDF page using the
    ``dict`` extraction mode which preserves bounding boxes."""
    try:
        data = page.get_text("dict")
    except Exception:
        return []
    blocks: list[TextBlock] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:  # 0 = text block
            continue
        lines_text = []
        for line in block.get("lines", []):
            spans_text = " ".join(span.get("text", "") for span in line.get("spans", []))
            if spans_text.strip():
                lines_text.append(spans_text.strip())
        if not lines_text:
            continue
        bbox = block.get("bbox", [0, 0, 0, 0])
        blocks.append(
            TextBlock(
                text="\n".join(lines_text),
                x0=float(bbox[0]),
                y0=float(bbox[1]),
                x1=float(bbox[2]),
                y1=float(bbox[3]),
            )
        )
    return blocks


def _detect_multicolumn(page, blocks: list[TextBlock]) -> tuple[bool, int, float]:
    """Detect whether the page has a multi-column layout.

    Returns ``(is_multicolumn, column_count, gap_x)`` where
    ``gap_x`` is the x-coordinate of the vertical gap between
    the columns.
    """
    page_width = float(page.rect.width)
    if page_width <= 0:
        return False, 1, 0.0

    mid_x = page_width / 2.0
    right_count = sum(1 for b in blocks if b.x0 >= mid_x)
    total = len(blocks)

    if total == 0:
        return False, 1, 0.0

    right_ratio = right_count / total

    # Heuristic 1: enough blocks on the right side.
    if right_ratio < _COLUMN_RATIO_THRESHOLD:
        return False, 1, 0.0

    # Heuristic 2: there is a vertical gap in the middle.
    gap_x = _find_vertical_gap(blocks, page_width)
    if gap_x is None:
        return False, 1, 0.0

    return True, 2, gap_x


def _find_vertical_gap(blocks: list[TextBlock], page_width: float) -> float | None:
    """Find the x-coordinate of a vertical gap in the middle of
    the page. A gap is a region where no text block overlaps
    horizontally and the gap is at least ``_GAP_MIN_RATIO`` of
    the page width.
    """
    if not blocks or page_width <= 0:
        return None

    # Build a histogram of horizontal block density.
    bin_count = 20
    bin_width = page_width / bin_count
    density = [0] * bin_count
    for b in blocks:
        start_bin = max(0, int(b.x0 / bin_width))
        end_bin = min(bin_count - 1, int(b.x1 / bin_width))
        for i in range(start_bin, end_bin + 1):
            density[i] += 1

    # Look for a gap in the middle 60% of the page.
    mid_start = int(bin_count * 0.2)
    mid_end = int(bin_count * 0.8)
    min_gap_bins = max(1, int(bin_count * _GAP_MIN_RATIO))

    # Find the longest run of zero-density bins in the middle.
    best_start = -1
    best_length = 0
    current_start = -1
    current_length = 0
    for i in range(mid_start, mid_end):
        if density[i] == 0:
            if current_start < 0:
                current_start = i
            current_length += 1
        else:
            if current_length > best_length:
                best_start = current_start
                best_length = current_length
            current_start = -1
            current_length = 0
    if current_length > best_length:
        best_start = current_start
        best_length = current_length

    if best_length >= min_gap_bins and best_start >= 0:
        gap_center = (best_start + best_length / 2.0) * bin_width
        return gap_center

    return None


def _reorder_by_columns(blocks: list[TextBlock], gap_x: float) -> list[TextBlock]:
    """Re-order blocks by column (left first, then right) and
    within each column by y-position (top to bottom)."""
    left = sorted(
        [b for b in blocks if b.x1 <= gap_x],
        key=lambda b: b.y0,
    )
    right = sorted(
        [b for b in blocks if b.x0 > gap_x],
        key=lambda b: b.y0,
    )
    reordered: list[TextBlock] = []
    for i, b in enumerate(left + right):
        reordered.append(
            TextBlock(
                text=b.text,
                x0=b.x0,
                y0=b.y0,
                x1=b.x1,
                y1=b.y1,
                reading_order=i,
            )
        )
    return reordered


__all__ = [
    "TextBlock",
    "LayoutResult",
    "extract_layout_aware_text",
]
