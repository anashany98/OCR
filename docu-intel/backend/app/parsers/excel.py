from __future__ import annotations

from pathlib import Path

from app.core.config import settings
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
    import pandas as pd

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
        # Promote the chosen row to header; drop everything above.
        frame.columns = [str(c).strip() for c in frame.iloc[header_idx]]
        frame = frame.iloc[header_idx + 1:].reset_index(drop=True)
        # Drop columns whose header ended up empty/duplicated.
        keep = [
            i for i, c in enumerate(frame.columns)
            if c and c.strip() and c.strip().lower() != "nan"
        ]
        frame = frame.iloc[:, keep]
        frame.columns = [c.strip() for c in frame.columns]

    # Replace NaN with empty string and strip.
    frame = frame.fillna("").astype(str)
    for col in frame.columns:
        frame[col] = frame[col].str.strip()

    # Drop rows that are now all empty.
    frame = frame[(frame != "").any(axis=1)].reset_index(drop=True)

    if frame.empty:
        return f"### Hoja: {sheet_name}\n\n*(Hoja sin datos)*"

    # If only one column or one row, fall back to a simple "label | valor" layout.
    if len(frame.columns) == 1 or len(frame) == 1:
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
        body_lines.append(
            "| " + " | ".join(_escape_md(row[c]) for c in frame.columns) + " |"
        )
    return "\n".join([f"### Hoja: {sheet_name}", "", header, sep, *body_lines])


def _escape_md(value: str) -> str:
    """Escape characters that would break a markdown table cell."""
    if value is None:
        return ""
    s = str(value).replace("\n", " ").replace("\r", " ").replace("|", "\\|").strip()
    # Collapse repeated whitespace.
    s = " ".join(s.split())
    return s or " "


def parse_excel(path: Path) -> ExtractedDocument:
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
    return ExtractedDocument(pages=pages)
