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

import contextlib
import logging
import threading
from functools import lru_cache

from app.core.config import settings
from app.ocr.base import BaseOCREngine

logger = logging.getLogger("app.ocr.factory")


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
    """Build and warm the configured worker-scoped OCR engine once.

    OCR-INIT-1 (Sprint 2): the previous implementation only
    triggered the lazy ``cached_property`` that loads the model
    weights. Paddle and Tesseract both do *additional* one-time
    work on the first real call:

    * PaddleOCR compiles the inference graph for the actual
      image dimensions. This can take 1-3 s the first time
      and another 0.5-1 s every time the image shape changes.
    * Tesseract allocates working memory proportional to the
      page resolution.
    * The vision LLM (Tier 4) loads its own model the first
      time it's instantiated.

    To avoid paying those costs on the *first real job* (which
    is the worst time to do it — the user is waiting), the
    preload hook now runs a synthetic-image extraction against
    the engine. The exercise is best-effort: any failure is
    swallowed and logged so a model that needs GPU config we
    don't have in this worker does not abort the boot.
    """
    engine = get_ocr_engine()
    _warm_ocr_engine(engine)
    _exercise(engine)
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
        _warm_ocr_engine(engine.fallback)
    if hasattr(engine, "pp_structure") and engine.pp_structure is not None:
        _warm_ocr_engine(engine.pp_structure)
    if hasattr(engine, "vlm_ocr") and engine.vlm_ocr is not None:
        _warm_ocr_engine(engine.vlm_ocr)
    if hasattr(engine, "_engine"):
        _ = engine._engine  # noqa: B018 - intentional touch to warm any lazy init
    if hasattr(engine, "_pipeline"):
        _ = engine._pipeline  # noqa: B018 - intentional touch to warm any lazy init


def _exercise(engine: BaseOCREngine) -> None:
    """Force the engine to do real work against a synthetic image.

    OCR-INIT-1 (Sprint 2): the model-weight download is half the
    warmup story. Paddle in particular compiles the inference
    graph lazily on the first call, sized to the actual image
    dimensions. A 64×64 white square is enough to trigger that
    compile pass and amortise the cost over the worker boot
    instead of the first real job.

    The exercise is best-effort. Any failure is logged at
    DEBUG level so a worker that lacks e.g. a GPU does not
    abort the boot. The next real call will trigger the same
    compile (just slower) but the worker is up and serving
    jobs.
    """
    import tempfile
    from pathlib import Path

    from app.core.config import settings

    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.debug("_exercise skipped: opencv / numpy not available")
        return

    if not settings.files_dir:
        logger.debug("_exercise skipped: settings.files_dir not configured")
        return

    tmp_dir = Path(tempfile.gettempdir())
    image_path = tmp_dir / f"ocr_preload_{engine.name}.png"
    try:
        # 64×64 white square with a tiny grey cross so the OCR
        # has SOMETHING to find (otherwise the cascade short-
        # circuits to "no text").
        img = np.full((64, 64, 3), 255, dtype=np.uint8)
        cv2.line(img, (16, 32), (48, 32), (200, 200, 200), 1)
        cv2.line(img, (32, 16), (32, 48), (200, 200, 200), 1)
        cv2.imwrite(str(image_path), img)
        engine.extract(image_path)
    except Exception as exc:
        logger.debug("OCR preload exercise failed (best-effort): %s", exc)
    finally:
        with contextlib.suppress(OSError):
            image_path.unlink(missing_ok=True)


__all__ = ["get_ocr_engine_class", "get_ocr_engine", "preload_ocr_engine", "clear_ocr_engine_cache"]
