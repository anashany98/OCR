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

    Keep the public contract narrow: parsers and tests can provide any
    object with ``extract(image_path)`` and ``name``. Newer built-in engines
    may accept optional hints through :func:`extract_with_language_hint`, but
    that is an extension, not a requirement for third-party/fake engines.
    """

    name: str

    def extract(self, image_path: Path) -> OCRResult:
        """Run OCR on a single image file and return the result."""
        ...


def extract_with_language_hint(
    engine: BaseOCREngine,
    image_path: Path,
    *,
    language: str | None = None,
) -> OCRResult:
    """Run OCR while preserving compatibility with strict engines.

    The original OCR contract was ``extract(image_path)``. Newer internal
    engines accept an optional ``language`` hint, but tests and external
    adapters may still implement the original signature. Try the richer call
    first and fall back only when Python tells us the keyword is unsupported.
    """
    try:
        return engine.extract(image_path, language=language)
    except TypeError as exc:
        if "unexpected keyword argument 'language'" not in str(exc):
            raise
        return engine.extract(image_path)


__all__ = ["OCRBlock", "OCRResult", "BaseOCREngine", "extract_with_language_hint"]
