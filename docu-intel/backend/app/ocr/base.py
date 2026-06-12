"""OCR engine abstraction.

Both Tesseract and (optionally) PaddleOCR implement :class:`BaseOCREngine`.
The active engine is selected by the ``OCR_ENGINE`` setting and instantiated
via :func:`app.ocr.factory.get_ocr_engine_class`.

Why an abstraction:
* The document parsers (image/pdf/router) only need ``extract(image_path)``
  plus an engine label to label the ``source_engine`` column.
* The factory lets tests inject a fake engine via
  ``monkeypatch.setattr(document_service, "get_ocr_engine_class", ...)``.
* We can swap OCR backends without touching the parsers or the worker code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class OCRBlock:
    """A single detected text block from an OCR pass.

    ``block_type`` carries the layout type when the backend can tell
    text from table from figure (PP-Structure / layout_parsing). Plain
    OCR engines leave it ``None``; parsers fall back to "text".
    """

    text: str
    confidence: float | None
    bbox: tuple[float, float, float, float] | None
    block_type: str | None = None


@dataclass
class OCRResult:
    """Aggregated output of a single OCR pass over one image.

    ``engine`` records which engine actually produced this result, so the
    cascading engine can transparently report "tesseract" on easy pages
    and "paddleocr" on hard pages. Parsers use this to label the
    ``DocumentBlock.source_engine`` column for the admin breakdown.
    """

    text: str
    confidence: float | None
    blocks: list[OCRBlock]
    engine: str = ""


class BaseOCREngine(Protocol):
    """Minimum contract every OCR engine must satisfy.

    The ``name`` attribute is the engine's identity (e.g. ``"tesseract"``,
    ``"paddleocr"``). The cascading engine has a dynamic ``name`` that
    reflects which underlying engine won the last call.
    """

    name: str

    def extract(self, image_path: Path) -> OCRResult:
        """Run OCR on a single image file and return the result."""
        ...


__all__ = ["OCRBlock", "OCRResult", "BaseOCREngine"]
