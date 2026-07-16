from __future__ import annotations

from pathlib import Path

from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage


def parse_plain_text(path: Path) -> ExtractedDocument:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return ExtractedDocument(
        pages=[
            ExtractedPage(
                page_number=1,
                text=text,
                ocr_content_kind="native_text",
                blocks=[
                    ExtractedBlock(
                        block_type="text",
                        text=text,
                        page_number=1,
                        confidence=1.0,
                        source_engine="plain_text",
                    )
                ],
            )
        ]
    )
