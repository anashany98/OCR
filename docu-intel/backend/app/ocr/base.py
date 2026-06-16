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

    The ``language`` keyword on :meth:`extract` is the page's
    detected language (e.g. ``"es"``, ``"en"``). Single-engine
    implementations can ignore it; the cascading engine uses it
    to look up the per-language adaptive thresholds (O2). The
    keyword is part of the contract (not just a cascading
    attribute) so the parser does not have to mutate the
    engine's instance state before each call, which used to
    race when multiple pages were processed in parallel.
    """

    name: str

    def extract(
        self,
        image_path: Path,
        *,
        language: str | None = None,
    ) -> OCRResult:
        """Run OCR on a single image file and return the result.

        ``language`` is an optional hint for engines that can
        bias their internal model (the cascading engine uses
        it for per-language thresholds). Default ``None`` means
        "no detection, use the document-wide defaults".
        """
        ...


__all__ = ["OCRBlock", "OCRResult", "BaseOCREngine"]
