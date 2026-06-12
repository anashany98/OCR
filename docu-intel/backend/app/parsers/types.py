from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExtractedBlock:
    block_type: str
    text: str
    page_number: int
    bbox: tuple[float, float, float, float] | None = None
    confidence: float | None = None
    source_engine: str | None = None


@dataclass
class ExtractedPage:
    page_number: int
    text: str
    width: float | None = None
    height: float | None = None
    image_path: str | None = None
    ocr_confidence: float | None = None
    # Which engine produced this page's text. One of: pymupdf, paddleocr, empty.
    # The ``empty`` label marks pages routed to OCR that still produced no
    # usable text — useful for spotting low-quality scans.
    ocr_engine: str | None = None
    blocks: list[ExtractedBlock] = field(default_factory=list)


@dataclass
class ExtractedDocument:
    pages: list[ExtractedPage]

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text)
