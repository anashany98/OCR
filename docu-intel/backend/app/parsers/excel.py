from __future__ import annotations

from pathlib import Path

from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage


def parse_excel(path: Path) -> ExtractedDocument:
    import pandas as pd

    pages: list[ExtractedPage] = []
    sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
    for index, (sheet_name, frame) in enumerate(sheets.items(), start=1):
        frame = frame.fillna("")
        lines = [f"Hoja: {sheet_name}"]
        for row in frame.itertuples(index=False):
            values = [str(value).strip() for value in row if str(value).strip()]
            if values:
                lines.append(" | ".join(values))
        text = "\n".join(lines)
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

