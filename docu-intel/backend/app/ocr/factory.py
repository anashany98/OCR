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
import threading

from app.core.config import settings
from app.ocr.base import BaseOCREngine


_engine_singleton: BaseOCREngine | None = None
_engine_lock = threading.RLock()


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

    if engine == "pp_structure":
        from app.ocr.pp_structure import PPStructureEngine

        return PPStructureEngine

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
                return _get_or_create_engine(_build_cascading_engine)

        return _CascadingFactory  # type: ignore[return-value]

    raise ValueError(
        f"Unknown ocr_engine: {engine!r}. Expected 'tesseract', 'paddleocr', 'cascading', or 'pp_structure'."
    )


def get_ocr_engine() -> BaseOCREngine:
    """Instantiate the configured engine. Convenience wrapper used by
    workers and tests."""
    return _get_or_create_engine(lambda: get_ocr_engine_class()())


def preload_ocr_engine() -> BaseOCREngine:
    """Build and warm the configured worker-scoped OCR engine once."""
    engine = get_ocr_engine()
    _warm_ocr_engine(engine)
    return engine


def clear_ocr_engine_cache() -> None:
    global _engine_singleton
    with _engine_lock:
        _engine_singleton = None
    get_ocr_engine_class.cache_clear()


def _get_or_create_engine(factory) -> BaseOCREngine:
    global _engine_singleton
    if _engine_singleton is not None:
        return _engine_singleton
    with _engine_lock:
        if _engine_singleton is None:
            _engine_singleton = factory()
        return _engine_singleton


def _build_cascading_engine() -> BaseOCREngine:
    from app.ocr.cascading import CascadingOCREngine
    from app.ocr.paddle import PaddleOCREngine
    from app.ocr.tesseract import TesseractOCREngine

    kwargs: dict[str, object] = dict(
        primary=TesseractOCREngine(
            lang=settings.tesseract_lang,
            oem=settings.tesseract_oem,
            psm=settings.tesseract_psm,
        ),
        fallback=PaddleOCREngine(lang=settings.paddle_lang),
        min_chars=settings.ocr_cascading_min_chars,
        min_confidence=settings.ocr_cascading_min_confidence,
    )
    if settings.ocr_cascading_use_pp_structure:
        from app.ocr.pp_structure import PPStructureEngine

        kwargs["pp_structure"] = PPStructureEngine(
            device=settings.pp_structure_device,
            lang=settings.pp_structure_lang,
        )
    if settings.enable_dots_mocr:
        from app.ocr.dots_mocr import DotsMOCRConfig, DotsMOCREngine

        kwargs["vlm_ocr"] = DotsMOCREngine(
            DotsMOCRConfig(
                enabled=True,
                endpoint=settings.dots_mocr_endpoint,
                api_key=settings.dots_mocr_api_key or None,
                timeout_seconds=settings.dots_mocr_timeout_seconds,
            )
        )
        kwargs["tier4_quality_threshold"] = settings.dots_mocr_quality_threshold
    return CascadingOCREngine(**kwargs)  # type: ignore[arg-type]


def _warm_ocr_engine(engine: BaseOCREngine) -> None:
    if hasattr(engine, "fallback"):
        _warm_ocr_engine(engine.fallback)  # type: ignore[attr-defined]
    if hasattr(engine, "pp_structure") and engine.pp_structure is not None:  # type: ignore[attr-defined]
        _warm_ocr_engine(engine.pp_structure)  # type: ignore[attr-defined]
    if hasattr(engine, "vlm_ocr") and engine.vlm_ocr is not None:  # type: ignore[attr-defined]
        _warm_ocr_engine(engine.vlm_ocr)  # type: ignore[attr-defined]
    if hasattr(engine, "_engine"):
        getattr(engine, "_engine")
    if hasattr(engine, "_pipeline"):
        getattr(engine, "_pipeline")


__all__ = ["get_ocr_engine_class", "get_ocr_engine", "preload_ocr_engine", "clear_ocr_engine_cache"]
