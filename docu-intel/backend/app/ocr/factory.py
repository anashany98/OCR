"""OCR engine factory.

The active engine is selected by the ``OCR_ENGINE`` setting. Three
modes are supported:

* ``"tesseract"``  — Tesseract 5 only (cheapest, fastest, CPU only).
* ``"paddleocr"``  — PaddleOCR 3.x only (heavyweight, GPU-accelerated).
* ``"cascading"``  — Tesseract first, PaddleOCR as fallback when the
                     primary result is too short or its confidence is
                     too low. **Default.**

The factory is cached with :func:`functools.lru_cache` so the same
engine instance is reused across calls in a worker. Tests patch this
symbol on the ``app.services.document_service`` module to inject a fake.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.ocr.base import BaseOCREngine


@lru_cache(maxsize=1)
def get_ocr_engine_class() -> type[BaseOCREngine]:
    """Return the OCR engine class configured by ``OCR_ENGINE``.

    Callers instantiate the returned class once per worker. For
    ``"cascading"`` we instantiate the wrapper, not the underlying
    engines, so the cascade owns both instances and shares the
    expensive PaddleOCR model between calls.
    """
    engine = settings.ocr_engine

    if engine == "tesseract":
        from app.ocr.tesseract import TesseractOCREngine

        return TesseractOCREngine

    if engine == "paddleocr":
        from app.ocr.paddle import PaddleOCREngine

        return PaddleOCREngine

    if engine == "cascading":
        from app.ocr.cascading import CascadingOCREngine
        from app.ocr.paddle import PaddleOCREngine
        from app.ocr.tesseract import TesseractOCREngine

        # The class returned here is technically a "class" (callable) so
        # existing call sites that do ``get_ocr_engine_class()()`` keep
        # working, but CascadingOCREngine is a regular class so each
        # call returns a fresh wrapper. We rely on the worker's
        # engine-being-a-singleton convention to avoid rebuilding.
        class _CascadingFactory:
            name = "cascading"

            def __new__(cls) -> BaseOCREngine:  # type: ignore[override]
                return CascadingOCREngine(
                    primary=TesseractOCREngine(
                        lang=settings.tesseract_lang,
                        oem=settings.tesseract_oem,
                        psm=settings.tesseract_psm,
                    ),
                    fallback=PaddleOCREngine(),
                    min_chars=settings.ocr_cascading_min_chars,
                    min_confidence=settings.ocr_cascading_min_confidence,
                )

        return _CascadingFactory  # type: ignore[return-value]

    raise ValueError(
        f"Unknown ocr_engine: {engine!r}. Expected 'tesseract', 'paddleocr', or 'cascading'."
    )


def get_ocr_engine() -> BaseOCREngine:
    """Instantiate the configured engine. Convenience wrapper used by
    workers and tests."""
    return get_ocr_engine_class()()


__all__ = ["get_ocr_engine_class", "get_ocr_engine"]
