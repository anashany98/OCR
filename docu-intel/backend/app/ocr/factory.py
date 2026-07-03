"""OCR engine factory.

The active engine is selected by the ``OCR_ENGINE`` setting. Three
modes are supported:

* ``"tesseract"``  — Tesseract 5 only (cheapest, fastest, CPU only).
* ``"paddleocr"``  — PaddleOCR 3.x only (heavyweight, GPU-accelerated).
* ``"cascading"``  — Tesseract first, PaddleOCR as fallback when the
                     primary result is too short or its confidence is
                     too low. **Default.**

The factory uses an explicit singleton (``_engine_singleton``) so the
same engine instance is reused across calls in a worker. Tests patch
``get_ocr_engine_class`` on the ``app.services.document_service``
module to inject a fake.
"""

from __future__ import annotations

import contextlib
import logging
import threading

from app.core.config import settings
from app.ocr.base import BaseOCREngine

logger = logging.getLogger("app.ocr.factory")


_engine_singleton: BaseOCREngine | None = None
_engine_class_singleton: type[BaseOCREngine] | None = None
_engine_lock = threading.RLock()


def get_ocr_engine_class() -> type[BaseOCREngine]:
    """Return the OCR engine class configured by ``OCR_ENGINE``.

    Callers instantiate the returned class once per worker. For
    ``"cascading"`` we instantiate the wrapper, not the underlying
    engines, so the cascade owns both instances and shares the
    expensive PaddleOCR model between calls.
    """
    global _engine_class_singleton
    if _engine_class_singleton is not None:
        return _engine_class_singleton

    engine = settings.ocr_engine

    if engine == "tesseract":
        from app.ocr.tesseract import TesseractOCREngine
        _engine_class_singleton = TesseractOCREngine

    elif engine == "paddleocr":
        from app.ocr.paddle import PaddleOCREngine
        _engine_class_singleton = PaddleOCREngine

    elif engine == "pp_structure":
        from app.ocr.pp_structure import PPStructureEngine
        _engine_class_singleton = PPStructureEngine

    elif engine == "cascading":
        _engine_class_singleton = get_cascading_engine

    else:
        raise ValueError(
            f"Unknown ocr_engine: {engine!r}. "
            "Expected 'tesseract', 'paddleocr', 'cascading', or 'pp_structure'."
        )

    return _engine_class_singleton


def get_cascading_engine() -> BaseOCREngine:
    """Build a CascadingOCREngine (singleton via _get_or_create_engine)."""
    return _get_or_create_engine(_build_cascading_engine)


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
    _warn_if_gpu_requested_but_unavailable(engine)
    _exercise(engine)
    return engine


def clear_ocr_engine_cache() -> None:
    global _engine_singleton, _engine_class_singleton
    with _engine_lock:
        _engine_singleton = None
        _engine_class_singleton = None


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

        # A2: a worker CPU booted with the GPU-only Tier 3 flag on
        # should NOT abort startup — the cascade still has Tier 1+2
        # available. ``PPStructureEngine.__init__`` refuses to build
        # on CPU with ``RuntimeError("GPU-only")``; we catch and
        # log so the worker degrades gracefully instead of taking
        # the whole Celery boot down.
        try:
            kwargs["pp_structure"] = PPStructureEngine(
                device=settings.pp_structure_device,
                lang=settings.pp_structure_lang,
            )
        except RuntimeError as exc:
            logger.warning(
                "PP-Structure disabled at runtime: %s. "
                "Cascade will run without Tier 3; check "
                "OCR_CASCADING_USE_PP_STRUCTURE / PP_STRUCTURE_DEVICE.",
                exc,
            )
            kwargs["pp_structure"] = None
    if settings.enable_dots_mocr:
        from app.ocr.dots_mocr import DotsMOCRConfig, DotsMOCREngine

        # A2 (parallel): same idea for Tier 4. If the endpoint or API
        # key is misconfigured, ``DotsMOCREngine`` is happy to
        # instantiate (validation is lazy, on first ``extract``), but a
        # defensive try keeps any future constructor-side validation
        # from aborting boot. The cascade falls back to Tier 1-3.
        try:
            kwargs["vlm_ocr"] = DotsMOCREngine(
                DotsMOCRConfig(
                    enabled=True,
                    endpoint=settings.dots_mocr_endpoint,
                    model=settings.dots_mocr_model or settings.vision_model,
                    api_key=settings.dots_mocr_api_key or None,
                    timeout_seconds=settings.dots_mocr_timeout_seconds,
                    domain=settings.dots_mocr_domain,
                )
            )
        except Exception as exc:  # noqa: BLE001 - any constructor failure
            logger.warning(
                "DotsMOCR (Tier 4) disabled at runtime: %s. "
                "Cascade will run without Tier 4; check DOTS_MOCR_* settings.",
                exc,
            )
            kwargs["vlm_ocr"] = None
        else:
            kwargs["tier4_quality_threshold"] = settings.dots_mocr_quality_threshold
    if settings.nuextract_enabled and settings.nuextract_tier4_enabled:
        try:
            from app.ocr.nuextract_ocr import NuExtractOCREngine

            nuextract = NuExtractOCREngine()
        except Exception as exc:  # noqa: BLE001 - any constructor failure
            logger.warning(
                "NuExtract3 (Tier 4) disabled at runtime: %s. "
                "Cascade will keep existing Tier 4 fallback if configured.",
                exc,
            )
        else:
            if kwargs.get("vlm_ocr") is not None:
                kwargs["tier4_fallback"] = kwargs["vlm_ocr"]
            kwargs["vlm_ocr"] = nuextract
            kwargs["tier4_quality_threshold"] = settings.dots_mocr_quality_threshold
    return CascadingOCREngine(**kwargs)  # type: ignore[arg-type]


def _warm_ocr_engine(engine: BaseOCREngine) -> None:
    """Warm up the engine with a timeout. If init hangs, log ERROR and
    mark the engine as unavailable rather than killing the worker."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    warmup_timeout = getattr(settings, "ocr_engine_warmup_timeout", 180)

    def _do_warm():
        if hasattr(engine, "fallback"):
            _warm_ocr_engine(engine.fallback)
        if hasattr(engine, "pp_structure") and engine.pp_structure is not None:
            _warm_ocr_engine(engine.pp_structure)
        if hasattr(engine, "vlm_ocr") and engine.vlm_ocr is not None:
            _warm_ocr_engine(engine.vlm_ocr)
        if hasattr(engine, "tier4_fallback") and engine.tier4_fallback is not None:
            _warm_ocr_engine(engine.tier4_fallback)
        if hasattr(engine, "_engine"):
            _ = engine._engine  # noqa: B018 - intentional touch to warm any lazy init
        if hasattr(engine, "_pipeline"):
            _ = engine._pipeline  # noqa: B018 - intentional touch to warm any lazy init

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_do_warm)
            future.result(timeout=warmup_timeout)
    except FuturesTimeout:
        logger.error(
            "OCR engine warmup timed out after %ds. "
            "Engine may be unavailable on first call.",
            warmup_timeout,
        )
    except Exception:
        logger.error("OCR engine warmup failed (best-effort)", exc_info=True)


def _warn_if_gpu_requested_but_unavailable(engine: BaseOCREngine) -> None:
    """M2 (Sprint 3): log a WARNING if any sub-engine was built with a
    GPU device string but the runtime CUDA stack is not actually
    visible to this worker.

    Without this check a worker booted with
    ``PADDLE_DEVICE=gpu`` on a CPU-only container (or one where
    the NVIDIA driver / CUDA libraries are missing) silently
    falls back to CPU on the first Paddle call. The first job
    still works, but it takes 10-50x longer than expected and
    the operator has no signal that something is wrong.

    We log at WARNING level and continue — the exercise path
    will fail anyway and the operator will see the failure in
    the logs, but this gives a precise, single-line message
    that says exactly what is misconfigured.
    """
    devices = _collect_gpu_device_strings(engine)
    if not devices:
        return

    try:
        import torch  # type: ignore[import-untyped]
    except ImportError:
        # If torch isn't even installed we can't tell, so don't
        # warn — the real failure will surface elsewhere.
        return

    if torch.cuda.is_available():
        return

    logger.warning(
        "OCR engine requested GPU device(s) %s but torch.cuda.is_available() "
        "is False. The engine will run on CPU; performance will be "
        "10-50x slower than expected. Check the container's NVIDIA "
        "driver and CUDA_VISIBLE_DEVICES.",
        sorted(devices),
    )


def _collect_gpu_device_strings(engine: BaseOCREngine) -> set[str]:
    """Walk an engine tree and return the set of non-None device strings
    that look like GPU requests (``gpu``, ``gpu:0``, ``cuda``, …)."""
    devices: set[str] = set()
    candidates = [engine]
    if hasattr(engine, "fallback"):
        candidates.append(engine.fallback)
    if hasattr(engine, "pp_structure") and engine.pp_structure is not None:
        candidates.append(engine.pp_structure)
    if hasattr(engine, "vlm_ocr") and engine.vlm_ocr is not None:
        candidates.append(engine.vlm_ocr)
    if hasattr(engine, "tier4_fallback") and engine.tier4_fallback is not None:
        candidates.append(engine.tier4_fallback)
    for cand in candidates:
        device = getattr(cand, "device", None)
        if isinstance(device, str) and device.lower().startswith(("gpu", "cuda")):
            devices.add(device)
    return devices


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


__all__ = ["get_ocr_engine_class", "get_ocr_engine", "get_cascading_engine", "preload_ocr_engine", "clear_ocr_engine_cache"]
