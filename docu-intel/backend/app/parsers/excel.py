from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.ocr.base import BaseOCREngine
from app.parsers.embedded_images import EmbeddedImage, extract_embedded_image_pages
from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage


def _detect_header_row(frame) -> int | None:
    """Pick the row that most likely holds the column headers. Strategy:
    take the first non-empty row whose first cell is non-empty and has a
    reasonable number of non-empty cells. We try the first 3 rows max so
    a budget with a long banner does not waste a slot on the header."""
    rows = list(frame.itertuples(index=False))
    for idx, row in enumerate(rows[:3]):
        non_empty = [str(v).strip() for v in row if str(v).strip()]
        if not non_empty:
            continue
        if len(non_empty) >= max(2, int(len(row) * 0.4)):
            return idx
    return None


def _frame_to_markdown(frame, sheet_name: str) -> str:
    """Convert a single sheet to a clean markdown table.

    - Detects the most likely header row.
    - Drops columns that are 100% empty.
    - Drops rows that are completely empty.
    - Falls back to "row | col | value" when no real table structure is
      found (e.g. only one non-empty cell per row)."""

    if frame.empty:
        return f"### Hoja: {sheet_name}\n\n*(Hoja vacia)*"

    # Drop columns that are entirely empty.
    frame = frame.dropna(axis=1, how="all")
    # Drop rows that are entirely empty.
    frame = frame.dropna(axis=0, how="all")
    if frame.empty:
        return f"### Hoja: {sheet_name}\n\n*(Hoja sin datos tras limpiar vacias)*"

    header_idx = _detect_header_row(frame)
    if header_idx is not None:
        # Save original state before attempting header promotion.
        original_frame = frame.copy()
        # Promote the chosen row to header; drop everything above.
        frame.columns = [str(c).strip() for c in frame.iloc[header_idx]]
        frame = frame.iloc[header_idx + 1 :].reset_index(drop=True)
        # If promoting the header left no data rows, the "header" was
        # actually the only data row (e.g. header=False in the source).
        # Restore the original frame and skip header promotion.
        if frame.empty:
            frame = original_frame
        else:
            # Drop columns whose header ended up empty/duplicated.
            keep = [
                i
                for i, c in enumerate(frame.columns)
                if c and c.strip() and c.strip().lower() != "nan"
            ]
            frame = frame.iloc[:, keep]
            frame.columns = [c.strip() for c in frame.columns]

    # Replace NaN with empty string and strip. Use positional indexing
    # (``frame.iloc[:, i]``) instead of label-based (``frame[col]``) so we
    # don't blow up when the header row had duplicate names — label-based
    # indexing on a DataFrame with duplicate columns returns a DataFrame,
    # which has no ``.str`` accessor and crashes with
    # ``'DataFrame' object has no attribute 'str'``.
    frame = frame.fillna("").astype(str)
    for i in range(len(frame.columns)):
        frame.iloc[:, i] = frame.iloc[:, i].str.strip()

    # Drop rows that are now all empty.
    frame = frame[(frame != "").any(axis=1)].reset_index(drop=True)

    if frame.empty:
        return f"### Hoja: {sheet_name}\n\n*(Hoja sin datos)*"

    # If only one column, fall back to a simple bullet list.
    if len(frame.columns) == 1:
        lines = [f"### Hoja: {sheet_name}", ""]
        col0 = frame.columns[0]
        for _, row in frame.iterrows():
            val = (row[col0] or "").strip()
            if val:
                lines.append(f"- {val}")
        return "\n".join(lines)

    # Build the markdown table.
    header = "| " + " | ".join(_escape_md(c) for c in frame.columns) + " |"
    sep = "| " + " | ".join("---" for _ in frame.columns) + " |"
    body_lines = []
    for _, row in frame.iterrows():
        body_lines.append("| " + " | ".join(_escape_md(row[c]) for c in frame.columns) + " |")
    return "\n".join([f"### Hoja: {sheet_name}", "", header, sep, *body_lines])


def _escape_md(value: str) -> str:
    """Escape characters that would break a markdown table cell."""
    if value is None:
        return ""
    s = str(value).replace("\n", " ").replace("\r", " ").replace("|", "\\|").strip()
    # Collapse repeated whitespace.
    s = " ".join(s.split())
    return s or " "


def _embedded_images(path: Path) -> list[EmbeddedImage]:
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=False, data_only=True)
    except Exception:
        return []
    images: list[EmbeddedImage] = []
    try:
        for sheet in workbook.worksheets:
            for index, image in enumerate(getattr(sheet, "_images", []), start=1):
                content = image._data()
                if isinstance(content, bytes):
                    image_format = str(getattr(image, "format", "png") or "png").lower()
                    images.append(EmbeddedImage(f"{sheet.title}_{index}.{image_format}", content))
    finally:
        workbook.close()
    return images


def parse_excel(
    path: Path,
    output_dir: Path | None = None,
    ocr_engine: BaseOCREngine | None = None,
) -> ExtractedDocument:
    import pandas as pd

    pages: list[ExtractedPage] = []
    sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
    if len(sheets) > settings.max_excel_sheets:
        raise ValueError(f"max_excel_sheets exceeded: {len(sheets)} > {settings.max_excel_sheets}")
    total_rows = sum(len(frame.index) for frame in sheets.values())
    if total_rows > settings.max_excel_rows:
        raise ValueError(f"max_excel_rows exceeded: {total_rows} > {settings.max_excel_rows}")
    for index, (sheet_name, frame) in enumerate(sheets.items(), start=1):
        text = _frame_to_markdown(frame, sheet_name)
        pages.append(
            ExtractedPage(
                page_number=index,
                text=text,
                ocr_content_kind="native_text",
                blocks=[
                    ExtractedBlock(
                        block_type="table",
                        text=text,
                        page_number=index,
                        confidence=1.0,
                        source_engine="pandas",
                    )
                ],
            )
        )
    pages.extend(
        extract_embedded_image_pages(
            _embedded_images(path),
            output_dir=output_dir,
            ocr_engine=ocr_engine,
            first_page_number=len(pages) + 1,
        )
    )
    return ExtractedDocument(pages=pages)
