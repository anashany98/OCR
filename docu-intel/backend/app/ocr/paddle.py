"""PaddleOCR engine (multi-GPU aware) — adapter delegate.

Heavyweight GPU-accelerated engine, used by the cascading OCR router as
the fallback when Tesseract's confidence / text length is too low. Kept
in the Docker image alongside Tesseract so the cascade can escalate to
it on hard cases (handwriting, low-quality scans, complex layouts).

The :class:`PaddleOCREngine` is now a thin wrapper around
:class:`app.ocr.paddle_adapter.PaddleOCRAdapter` so that all the version
drift / API detection / output normalisation logic lives in one place
(the adapter). The engine keeps the same public surface
(:pyattr:`name` == ``"paddleocr"``, :meth:`extract`) so existing
callers, tests and the cascade do not need to change.

Multi-GPU support: each Celery worker has ``CUDA_VISIBLE_DEVICES``
pinned to a single card (see docker-compose). PaddleOCR's underlying
Paddle picks it up automatically. The cross-process init lock lives
inside the adapter.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from app.core.config import settings
from app.ocr.adapter import PaddleOCRAdapter  # re-export from the package __init__
from app.ocr.base import OCRBlock, OCRResult
from app.ocr.paddle_adapter import (
    PaddleOCRAdapter as _Adapter,
    paddleocr_init_lock,
    polygon_to_bbox,
)
from app.ocr.preprocess import preprocess_for_paddle
from app.services.metrics import track_ocr_duration


logger = logging.getLogger("app.ocr.paddle")


def _get_gpu_device() -> str | None:
    """Obtiene el GPU device del environment variable."""
    cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES", None)
    if cuda_visible is None:
        return None
    devices = cuda_visible.split(",")
    if devices and devices[0].strip():
        return devices[0].strip()
    return None


def _format_paddle_device(device_id: str | None) -> str | None:
    """Format a CUDA device id into the string PaddleOCR expects.

    * ``None`` or empty → returns ``None``.
    * ``"gpu:0"``, ``"cpu"``, ``"xpu:1"``, ``"npu:2"`` → returned as-is.
    * A bare device index like ``"0"`` → returned as ``"gpu:0"``.
    """
    if not device_id:
        return None
    if device_id.startswith(("gpu", "cpu", "xpu", "npu")):
        return device_id
    return f"gpu:{device_id}"


# Module-level alias for backwards compatibility — the legacy tests
# imported ``_polygon_to_bbox`` directly from ``app.ocr.paddle``.
_polygon_to_bbox = polygon_to_bbox

# Backwards-compat constant kept at module level for the legacy tests
# (``tests/test_paddle_init_timeout.py``) that import
# ``_PADDLE_INIT_TIMEOUT_SECONDS`` from ``app.ocr.paddle``. The
# adapter owns the actual value; this alias is the same constant.
_PADDLE_INIT_TIMEOUT_SECONDS = 120.0


class PaddleOCREngine:
    """PaddleOCR 3.x engine. Implements the :class:`BaseOCREngine` protocol.

    Delegates all the work to :class:`PaddleOCRAdapter` so the version
    detection / output normalisation logic lives in one place. Keeps the
    legacy ``_engine`` cached property for backwards compatibility with
    tests that monkeypatch it.
    """

    name: str = "paddleocr"

    def __init__(self, lang: str | None = None, device: str | None = None) -> None:
        self.lang = lang or settings.paddle_lang
        self.device = device or _format_paddle_device(_get_gpu_device())
        self._adapter = _Adapter(
            lang=self.lang,
            device=self.device,
            allow_unknown_output=settings.paddle_allow_unknown_output_format,
            log_runtime_info=settings.paddle_log_runtime_info,
            settings=settings,
        )

    @property
    def _engine(self):
        """Backwards-compatible accessor that exposes the underlying PaddleOCR.

        Returns the cached PaddleOCR instance if one has already been
        built, otherwise ``None``. We deliberately do **not** trigger the
        lazy init here so ``monkeypatch.setattr(engine, "_engine", ...)``
        (which internally does a ``getattr`` first) does not pay the
        ~500 MB model download on every test run.
        """
        return self._adapter._holder._instance

    def _init_engine_with_timeout(self):  # pragma: no cover - thin shim
        """Backwards-compat shim for tests that monkeypatched the
        legacy ``PaddleOCREngine._init_engine_with_timeout`` method."""
        return self._adapter._holder.get()

    def extract(self, image_path: Path) -> OCRResult:
        start = time.perf_counter()
        ocr_path = preprocess_for_paddle(image_path)
        try:
            result = self._adapter.run(ocr_path)
        finally:
            track_ocr_duration(time.perf_counter() - start)
        # The adapter stamps ``engine="paddleocr"``; the engine itself is
        # what the cascade / parsers look at, so keep the existing name.
        if result.engine != self.name:
            result.engine = self.name
        return result

    # -----------------------------------------------------------------
    # Legacy helpers — re-exported for tests that monkeypatched the
    # pre-refactor ``PaddleOCREngine`` API.
    # -----------------------------------------------------------------

    def _parse_ocr_line(self, line: object):  # pragma: no cover - thin shim
        """Backwards-compatible wrapper around the adapter's legacy parser."""
        from app.ocr.paddle_adapter import _extract_block_from_legacy_line

        return _extract_block_from_legacy_line(line)

    @staticmethod
    def _polygon_to_bbox(polygon: object):  # pragma: no cover - thin shim
        """Backwards-compatible wrapper around :func:`polygon_to_bbox`."""
        return polygon_to_bbox(polygon)


__all__ = [
    "PaddleOCREngine",
    "PaddleOCRAdapter",
    "paddleocr_init_lock",
    "polygon_to_bbox",
    "_get_gpu_device",
    "_format_paddle_device",
    # Re-exports for backwards compatibility with tests that previously
    # imported OCRBlock/OCRResult/_polygon_to_bbox/_parse_ocr_line from
    # ``app.ocr.paddle``.
    "OCRBlock",
    "OCRResult",
    "_polygon_to_bbox",
    "_parse_ocr_line",
]
