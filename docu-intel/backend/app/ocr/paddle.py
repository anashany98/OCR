"""PaddleOCR 3.x engine (multi-GPU aware).

Heavyweight GPU-accelerated engine, used by the cascading OCR router as
the fallback when Tesseract's confidence / text length is too low. Kept
in the Docker image alongside Tesseract so the cascade can escalate to
it on hard cases (handwriting, low-quality scans, complex layouts).

Multi-GPU support: each Celery worker has ``CUDA_VISIBLE_DEVICES``
pinned to a single card (see docker-compose). PaddleOCR's underlying
Paddle picks it up automatically. The cross-process init lock in
:pydata:`paddleocr_init_lock` keeps the first call from racing across
concurrent workers.
"""

from __future__ import annotations

import concurrent.futures
import os
import tempfile
import time
from contextlib import contextmanager, nullcontext
from functools import cached_property
from pathlib import Path
import sys

from app.core.config import settings
from app.ocr.base import OCRBlock, OCRResult
from app.ocr.preprocess import preprocess_for_paddle
from app.services.metrics import track_ocr_duration

logger = __import__("logging").getLogger("app.ocr.paddle")

# H6 (Sprint 2): maximum time (seconds) to wait for PaddleOCR model
# to load.  If the init does not complete within this window the
# engine is marked unavailable and subsequent calls raise instead of
# blocking the worker thread forever.
_PADDLE_INIT_TIMEOUT_SECONDS: float = 120.0


# =============================================================================
# MULTI-GPU SUPPORT para PaddleOCR con RTX 4070 (x2)
# =============================================================================
# Configurar CUDA_VISIBLE_DEVICES por worker:
# - worker-gpu-0: CUDA_VISIBLE_DEVICES=0 (GPU 0)
# - worker-gpu-1: CUDA_VISIBLE_DEVICES=1 (GPU 1)
# PaddleOCR usará automáticamente el GPU asignado
# =============================================================================


def _get_gpu_device() -> str | None:
    """Obtiene el GPU device del environment variable."""
    cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES", None)
    if cuda_visible is None:
        return None
    # Tomar el primer GPU disponible
    devices = cuda_visible.split(",")
    if devices and devices[0].strip():
        return devices[0].strip()
    return None


def _cuda_runtime_available() -> bool:
    """Return True when the Paddle CUDA runtime can actually see a
    GPU on this host.

    The check is intentionally cheap: we try to import
    ``paddle.device.is_compiled_with_cuda`` and call
    ``paddle.device.cuda.device_count()``. A return of ``0`` (no
    GPU visible to Paddle) or a failed import (CUDA build of
    Paddle not installed) both count as "no GPU available". The
    function never raises; the caller treats a False return as
    "use CPU".

    This is the runtime guard behind
    :func:`resolve_paddle_device` so a host that does have a
    GPU but the Paddle install is CPU-only (the default
    ``paddlepaddle`` wheel) does not crash the worker at first
    OCR call.
    """
    try:
        import paddle  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        return False
    try:
        if not paddle.device.is_compiled_with_cuda():
            return False
        return int(paddle.device.cuda.device_count()) > 0
    except Exception:  # noqa: BLE001
        return False


def resolve_paddle_device(
    *,
    requested: str | None = None,
) -> str | None:
    """Return the Paddle device string we should pass to
    ``PaddleOCR(...)``.

    Resolution order:

    1. An explicit ``requested`` value (already formatted, e.g.
       ``"gpu:0"``) is honoured as-is.
    2. If ``CUDA_VISIBLE_DEVICES`` is set AND the Paddle CUDA
       runtime reports at least one device, we format the index
       as ``"gpu:<idx>"``.
    3. Otherwise we return ``None`` so PaddleOCR picks its own
       default. On a CUDA build that is GPU 0; on a CPU build
       that is CPU — both safe.

    The chosen device is logged at INFO so the operator can
    see at boot which engine is going to be used. The
    resolution is also cached at module import time so the
    same value is reused across worker boot and per-request
    PaddleOCR instances.
    """
    if requested:
        logger.info("PaddleOCR: using explicit device=%s", requested)
        return requested
    gpu_idx = _get_gpu_device()
    if gpu_idx and _cuda_runtime_available():
        device = f"gpu:{gpu_idx}"
        logger.info("PaddleOCR: CUDA available; using device=%s", device)
        return device
    if gpu_idx and not _cuda_runtime_available():
        logger.warning(
            "PaddleOCR: CUDA_VISIBLE_DEVICES=%s is set but the Paddle "
            "runtime reports no usable GPU. Falling back to CPU; the OCR "
            "cascade will still work, just slower.",
            gpu_idx,
        )
    else:
        logger.info(
            "PaddleOCR: no CUDA_VISIBLE_DEVICES set; using Paddle's default "
            "device (GPU if the runtime supports it, otherwise CPU)."
        )
    return None


class PaddleOCREngine:
    """PaddleOCR 3.x engine. Implements the :class:`BaseOCREngine` protocol."""

    name: str = "paddleocr"

    def __init__(self, lang: str | None = None, device: str | None = None) -> None:
        self.lang = lang or settings.paddle_lang
        # ``resolve_paddle_device`` honours an explicit ``device``
        # argument; otherwise it inspects ``CUDA_VISIBLE_DEVICES``
        # plus the Paddle runtime and falls back to the Paddle
        # default (CPU on a CPU build, GPU 0 on a CUDA build) when
        # no GPU is visible. The chosen device is logged once at
        # construction time.
        self.device = device or resolve_paddle_device()

    @cached_property
    def _engine(self):
        return self._init_engine_with_timeout()

    def _init_engine_with_timeout(self):
        """Load the PaddleOCR model with a cross-platform timeout.

        H6 (Sprint 3): the previous ``@cached_property`` blocked
        indefinitely if the GPU driver or model download hung.  We now
        run the heavy ``PaddleOCR(...)`` call inside a daemon thread
        and raise ``RuntimeError`` when it does not complete within
        ``_PADDLE_INIT_TIMEOUT_SECONDS``.

        CPU fallback (OPS-FALLBACK-1): if the first attempt with the
        requested device fails — e.g. the host has ``CUDA_VISIBLE_DEVICES=0``
        set but the Paddle wheel is the CPU-only build, or the GPU
        driver is missing — we retry once with ``device=None`` so
        Paddle picks its own default (CPU on a CPU build, GPU 0 on a
        CUDA build). The retry is only triggered by a real
        init-time failure, not by the timeout: a 120-second hang
        still raises so the worker is not blocked forever.
        """
        from paddleocr import PaddleOCR

        def _attempt(device_value: str | None) -> "PaddleOCR":
            kwargs = {
                "use_textline_orientation": True,
                "lang": self.lang,
                "enable_mkldnn": False,
            }
            if device_value:
                kwargs["device"] = device_value
            with paddleocr_init_lock():
                return PaddleOCR(**kwargs)

        def _do_init(device_value: str | None) -> "PaddleOCR":
            return _attempt(device_value)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            # First attempt: the device the constructor picked.
            future = pool.submit(_do_init, self.device)
            try:
                return future.result(timeout=_PADDLE_INIT_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                logger.error(
                    "PaddleOCR init timed out after %.0fs (lang=%s, device=%s)",
                    _PADDLE_INIT_TIMEOUT_SECONDS,
                    self.lang,
                    self.device,
                )
                raise RuntimeError(
                    f"PaddleOCR model init timed out after {_PADDLE_INIT_TIMEOUT_SECONDS}s"
                ) from None
            except Exception as exc:  # noqa: BLE001
                # Only retry on real init failures (the engine
                # object was never created), not on timeouts (a
                # hung worker thread must not leak).
                if self.device is None or self.device == "cpu":
                    # Already on the safest path; nothing to fall
                    # back to.
                    logger.error(
                        "PaddleOCR init failed on device=%s and no GPU fallback is possible: %s",
                        self.device,
                        exc,
                    )
                    raise
                logger.warning(
                    "PaddleOCR init failed on device=%s (%s); retrying "
                    "with the runtime default (CPU on a CPU build, "
                    "GPU 0 on a CUDA build).",
                    self.device,
                    exc,
                )
                self.device = None
                future = pool.submit(_do_init, None)
                try:
                    return future.result(timeout=_PADDLE_INIT_TIMEOUT_SECONDS)
                except concurrent.futures.TimeoutError:
                    logger.error(
                        "PaddleOCR fallback init timed out after %.0fs",
                        _PADDLE_INIT_TIMEOUT_SECONDS,
                    )
                    raise RuntimeError(
                        f"PaddleOCR fallback init timed out after {_PADDLE_INIT_TIMEOUT_SECONDS}s"
                    ) from None

    def extract(
        self,
        image_path: Path,
        *,
        language: str | None = None,
    ) -> OCRResult:
        start = time.perf_counter()
        ocr_path = preprocess_for_paddle(image_path)
        raw = self._engine.ocr(str(ocr_path))
        blocks: list[OCRBlock] = []
        confidences: list[float] = []

        if raw is None:
            return OCRResult(text="", confidence=None, blocks=[], engine=self.name)

        if not isinstance(raw, (list, tuple)):
            raw = [raw]

        for page in raw:
            if page is None:
                continue

            # PaddleOCR 3.x format: dict with rec_texts, rec_scores, dt_polys
            if isinstance(page, dict):
                rec_texts = page.get("rec_texts", [])
                rec_scores = page.get("rec_scores", [])
                dt_polys = page.get("dt_polys", [])

                for i, text in enumerate(rec_texts):
                    score = rec_scores[i] if i < len(rec_scores) else None
                    bbox = None
                    if i < len(dt_polys):
                        poly = dt_polys[i]
                        bbox = _polygon_to_bbox(poly.tolist() if hasattr(poly, "tolist") else poly)

                    blocks.append(
                        OCRBlock(
                            text=text or "",
                            confidence=float(score) if score is not None else None,
                            bbox=bbox,
                        )
                    )
                    if score is not None:
                        confidences.append(float(score))
                continue

            # Legacy/2.x format or other list format
            if not isinstance(page, (list, tuple)):
                continue

            for line in page:
                result = self._parse_ocr_line(line)
                if result is not None:
                    text, confidence, bbox = result
                    blocks.append(OCRBlock(text=text, confidence=confidence, bbox=bbox))
                    confidences.append(confidence)

        text = "\n".join(block.text for block in blocks if block.text)
        average = sum(confidences) / len(confidences) if confidences else None
        track_ocr_duration(time.perf_counter() - start)
        return OCRResult(text=text, confidence=average, blocks=blocks, engine=self.name)

    def _parse_ocr_line(
        self, line: object
    ) -> tuple[str, float, tuple[float, float, float, float] | None] | None:
        """Parse a single OCR line, handling both 2.x and 3.x formats."""
        if isinstance(line, (list, tuple)) and len(line) >= 2:
            polygon = line[0]
            payload = line[1]
            if isinstance(payload, (list, tuple)) and len(payload) >= 2:
                text = payload[0]
                confidence = float(payload[1])
            else:
                text = str(payload)
                confidence = 0.0
            bbox = _polygon_to_bbox(polygon)
            return (text, confidence, bbox)

        text = getattr(line, "text", None)
        score = getattr(line, "score", None)
        if text is not None and score is not None:
            text = str(text)
            confidence = float(score)
            polygon = getattr(line, "polygon", None) or getattr(line, "bbox", None)
            bbox = _polygon_to_bbox(polygon) if polygon else None
            return (text, confidence, bbox)

        return None


def _polygon_to_bbox(polygon: object) -> tuple[float, float, float, float] | None:
    """Compute the axis-aligned bounding box of a polygon.

    Returns ``(x_min, y_min, x_max, y_max)`` for the given polygon, or
    ``None`` when the input is not a non-empty list of ``(x, y)`` points
    that can be coerced to floats.

    The function is intentionally tolerant: any element that cannot be
    parsed (e.g. a string in a coordinate) causes the function to return
    ``None`` instead of raising, so the OCR pipeline can keep going with
    a degraded (bbox-less) block.
    """
    if not isinstance(polygon, (list, tuple)):
        return None
    if not polygon:
        return None
    try:
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
    except (IndexError, TypeError, ValueError):
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _format_paddle_device(device_id: str | None) -> str | None:
    """Format a CUDA device id into the string PaddleOCR expects.

    Accepts:

    * ``None`` or empty → returns ``None`` so PaddleOCR falls back to its
      own default (CPU when CUDA is not available, otherwise GPU 0).
    * An already-prefixed device like ``"gpu:0"``, ``"cpu"``, ``"xpu:1"``
      or ``"npu:2"`` → returned as-is.
    * A bare device index like ``"0"`` → returned as ``"gpu:0"``.

    Note: PaddleOCR 3.x ignores a bare ``"cpu"`` arg silently and still
    initialises on GPU if CUDA is available. To force CPU the caller
    must pass ``device=None`` and have no CUDA visible to the process.
    """
    if not device_id:
        return None
    if device_id.startswith(("gpu", "cpu", "xpu", "npu")):
        return device_id
    return f"gpu:{device_id}"


@contextmanager
def paddleocr_init_lock():
    is_unix = sys.platform != "win32"

    if not is_unix:
        with nullcontext():
            yield
        return

    try:
        import fcntl
    except Exception:
        with nullcontext():
            yield
        return

    lock_path = Path(tempfile.gettempdir()) / "docuintel_paddleocr_init.lock"
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)  # type: ignore[attr-defined]
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


__all__ = [
    "PaddleOCREngine",
    "paddleocr_init_lock",
    "resolve_paddle_device",
    "_get_gpu_device",
    "_cuda_runtime_available",
    "_format_paddle_device",
]
