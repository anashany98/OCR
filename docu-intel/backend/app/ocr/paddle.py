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
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager, nullcontext
from functools import cached_property
from pathlib import Path

from app.core.config import settings
from app.ocr.base import OCRBlock, OCRResult
from app.ocr.preprocess import preprocess_adaptive
from app.services.metrics import track_ocr_duration

logger = logging.getLogger("app.ocr.paddle")

# H6 (Sprint 2): maximum time (seconds) to wait for PaddleOCR model
# to load.  If the init does not complete within this window the
# engine is marked unavailable and subsequent calls raise instead of
# blocking the worker thread forever.
_PADDLE_INIT_TIMEOUT_SECONDS: float = 120.0

# Process-level flag: once init fails or times out, all subsequent
# PaddleOCREngine instances in this process skip init immediately.
# This prevents the VRAM leak from repeated timeout → orphan thread cycles.
# FASE 3.1: TTL de 30 min para permitir reintento tras un spike temporal.
_PROCESS_INIT_FAILED: bool = False
_PROCESS_INIT_FAILED_AT: float = 0.0  # timestamp of failure
_PROCESS_INIT_TTL_SECONDS: float = 1800.0  # 30 minutes


def _is_init_failed() -> bool:
    """Check if init is permanently failed. Auto-reset after TTL."""
    global _PROCESS_INIT_FAILED, _PROCESS_INIT_FAILED_AT
    if not _PROCESS_INIT_FAILED:
        return False
    if time.monotonic() - _PROCESS_INIT_FAILED_AT > _PROCESS_INIT_TTL_SECONDS:
        logger.info(
            "PaddleOCR init failure TTL expired (%.0fs), allowing retry",
            _PROCESS_INIT_TTL_SECONDS,
        )
        _PROCESS_INIT_FAILED = False
        _PROCESS_INIT_FAILED_AT = 0.0
        return False
    return True


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


def gpu_has_headroom(minimum_free_memory_mb: int | None = None) -> bool:
    """Return whether the worker's assigned GPU has enough free VRAM.

    CUDA visibility alone is insufficient on a desktop machine: LM Studio or
    another local model may already occupy almost all VRAM.  Starting Paddle
    in that condition leads to a cgroup SIGKILL, which loses the Celery child
    and stalls the queue.  A failed probe is deliberately treated as no
    headroom, so the cascade can use its safe Tesseract/VLM path.
    """
    device = _get_gpu_device()
    if device is None:
        return False
    minimum = (
        settings.paddle_gpu_min_free_memory_mb
        if minimum_free_memory_mb is None
        else minimum_free_memory_mb
    )
    visible_device = os.environ.get("NVIDIA_VISIBLE_DEVICES", device).strip()
    if not visible_device or visible_device.lower() in {"all", "void", "none"}:
        visible_device = device
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--id=" + visible_device.split(",")[0],
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
        free_memory_mb = int(result.stdout.strip().splitlines()[0])
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, IndexError):
        logger.warning("Unable to determine free VRAM; disabling GPU OCR for this worker")
        return False
    if free_memory_mb < minimum:
        logger.warning(
            "GPU OCR deferred: only %s MiB VRAM free on GPU %s (minimum %s MiB)",
            free_memory_mb,
            visible_device,
            minimum,
        )
        return False
    return True


class PaddleOCREngine:
    """PaddleOCR 3.x engine. Implements the :class:`BaseOCREngine` protocol."""

    name: str = "paddleocr"
    # F3-03: serialise GPU inference — PaddleOCR is not thread-safe for
    # concurrent calls on the same GPU device.
    _inference_lock: threading.Lock = threading.Lock()

    def __init__(self, lang: str | None = None, device: str | None = None) -> None:
        self.lang = lang or settings.paddle_lang
        self.device = device or _format_paddle_device(_get_gpu_device())
        # O6: when the lazy init fails or times out the engine is
        # marked unavailable so subsequent calls raise a clear error
        # instead of re-entering the broken state.
        self._init_failed: bool = False

    @cached_property
    def _engine(self):
        global _PROCESS_INIT_FAILED, _PROCESS_INIT_FAILED_AT
        if _is_init_failed() or getattr(self, "_init_failed", False):
            raise RuntimeError("PaddleOCR engine is unavailable: previous init attempt failed")
        return self._init_engine_with_timeout()

    def _init_engine_with_timeout(self):
        """Load the PaddleOCR model with a cross-platform timeout.

        H6 (Sprint 3) / O6 fix: the previous implementation ran the
        heavy ``PaddleOCR(...)`` call inside a bare
        ``threading.Thread(daemon=False)`` joined with a timeout. When
        the timeout expired the join returned but the thread kept
        running (a stuck C-level ``PaddleOCR`` constructor holds the
        GIL and cannot be interrupted from Python). The orphan thread
        then continued allocating VRAM on the worker's GPU, slowly
        saturating the card across ``max_tasks_per_child`` cycles.

        The fix moves the work into a *dedicated, disposable*
        ``ThreadPoolExecutor`` and waits on ``future.result(timeout=...)``.
        If the timeout fires we:

        * mark the engine as unavailable (``_init_failed = True``) so
          subsequent ``extract`` calls raise a clear error instead of
          re-entering the same broken state;
        * call ``future.cancel()`` (best-effort — a PaddleOCR
          constructor that has already started loading will not honor
          the cancellation, but a still-pending future will);
        * let the ``with`` block exit so the executor is shut down. The
          abandoned worker thread (if any) lives inside the executor's
          private pool, NOT in the worker's shared pool, so it cannot
          be reused to serve another task and its VRAM cost is bounded
          to a single failed init per engine instance.

        The proper long-term fix is to do the init synchronously in
        ``worker_process_init`` (the worker's main thread, before it
        accepts jobs); the cascade's ``preload_ocr_engine`` already
        attempts that, but this per-instance timeout keeps the cascade
        safe even if the preload step is skipped or fails.
        """
        from paddleocr import PaddleOCR

        kwargs = {
            "use_textline_orientation": True,
            "lang": self.lang,
            "enable_mkldnn": False,
        }
        if self.device:
            kwargs["device"] = self.device
        # FP16 / TensorRT FP16: PaddleOCR 3.x accepts precision="fp16" via
        # **kwargs (-> pptrt_precision -> run_mode="trt_fp16"). ~1.5-2x faster
        # on Tensor-Core GPUs (RTX 4070). Gated by setting so CPU stays fp32.
        #
        # NOTE: self.device (e.g. "gpu:0") is already passed as kwargs["device"]
        # above. PaddleOCR 3.5.0 selects the GPU from that string — do NOT pass
        # "device_id" (removed): it is no longer a valid kwarg in 3.5.0 and
        # raises "Unknown argument: device_id", which silently disabled Tier 2
        # on all GPU workers and left the RTX 4070s idle. Likewise "enable_newir"
        # is omitted: under Paddle 3.3.1 it triggers
        # "ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute]"
        # in PP-Structure's oneDNN path, forcing every Tier 3 init to time out.
        if self.device and "gpu" in str(self.device).lower() and settings.paddle_use_fp16:
            kwargs["precision"] = "fp16"

        # max_workers=1 keeps the disposable executor constrained to a
        # single in-flight init at a time per engine instance, and we want
        # the abandoned thread (on timeout) isolated from the worker's
        # own pool.
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="paddleocr-init"
        ) as executor:
            init_future = executor.submit(self._run_paddleocr_init, PaddleOCR, kwargs)
            try:
                return init_future.result(timeout=_PADDLE_INIT_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                global _PROCESS_INIT_FAILED, _PROCESS_INIT_FAILED_AT
                init_future.cancel()
                _PROCESS_INIT_FAILED = True
                _PROCESS_INIT_FAILED_AT = time.monotonic()
                logger.error(
                    "PaddleOCR init timed out after %.0fs (lang=%s, device=%s). "
                    "Process marked — all future PaddleOCR inits will skip for %.0fs.",
                    _PADDLE_INIT_TIMEOUT_SECONDS,
                    self.lang,
                    self.device,
                    _PROCESS_INIT_TTL_SECONDS,
                )
                self._init_failed = True
                raise RuntimeError(
                    f"PaddleOCR model init timed out after {_PADDLE_INIT_TIMEOUT_SECONDS}s"
                ) from None

    def _run_paddleocr_init(self, paddleocr_cls, kwargs):
        """Run the PaddleOCR constructor under the cross-process init lock.

        Extracted from ``_init_engine_with_timeout`` so the body of the
        future is a named method (easier to mock in tests) and so the
        ``paddleocr_init_lock`` context manager is always entered from
        the worker thread, matching the cross-process exclusion the lock
        exists to provide.
        """
        with paddleocr_init_lock():
            return paddleocr_cls(**kwargs)

    def extract(self, image_path: Path) -> OCRResult:
        start = time.perf_counter()
        ocr_path = preprocess_adaptive(image_path, engine=self.name)
        try:
            # F3-03: serialise inference on shared GPU
            with self._inference_lock:
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
            return OCRResult(text=text, confidence=average, blocks=blocks, engine=self.name)
        finally:
            track_ocr_duration(time.perf_counter() - start)
            if ocr_path != image_path:
                ocr_path.unlink(missing_ok=True)

    def extract_batch(
        self, image_paths: list[Path], max_workers: int = 2
    ) -> list[OCRResult]:
        """Process multiple pages using PaddleOCR's batch mode.

        PaddleOCR 3.x can process multiple images in one call, which
        is more GPU-efficient than serial processing. We preprocess
        all images first, then pass them to the OCR engine in batch.
        """
        if len(image_paths) <= 1:
            return [self.extract(image_paths[0])] if image_paths else []

        start = time.perf_counter()
        logger.info("PaddleOCR batch: preprocessing %d pages", len(image_paths))

        # Preprocess all images
        from app.ocr.preprocess import preprocess_adaptive
        ocr_paths = []
        temp_files = []
        for path in image_paths:
            ocr_path = preprocess_adaptive(path, engine=self.name)
            ocr_paths.append(str(ocr_path))
            if ocr_path != path:
                temp_files.append(ocr_path)

        try:
            # PaddleOCR batch mode: pass list of image paths
            raw = self._engine.ocr(ocr_paths)

            results = []
            if raw is None:
                results = [OCRResult(text="", confidence=None, blocks=[], engine=self.name) for _ in image_paths]
            else:
                if not isinstance(raw, list):
                    raw = [raw]
                for page_raw in raw:
                    results.append(self._parse_batch_page(page_raw))

            return results
        finally:
            track_ocr_duration(time.perf_counter() - start)
            for tf in temp_files:
                tf.unlink(missing_ok=True)

    def _parse_batch_page(self, page_raw) -> OCRResult:
        """Parse a single page result from batch processing."""
        blocks: list[OCRBlock] = []
        confidences: list[float] = []

        if page_raw is None:
            return OCRResult(text="", confidence=None, blocks=[], engine=self.name)

        # PaddleOCR 3.x format: dict with rec_texts, rec_scores, dt_polys
        if isinstance(page_raw, dict):
            rec_texts = page_raw.get("rec_texts", [])
            rec_scores = page_raw.get("rec_scores", [])
            dt_polys = page_raw.get("dt_polys", [])

            for i, text in enumerate(rec_texts):
                score = rec_scores[i] if i < len(rec_scores) else None
                bbox = None
                if i < len(dt_polys):
                    poly = dt_polys[i]
                    bbox = _polygon_to_bbox(poly.tolist() if hasattr(poly, "tolist") else poly)

                blocks.append(OCRBlock(
                    text=text or "",
                    confidence=float(score) if score is not None else None,
                    bbox=bbox,
                ))
                if score is not None:
                    confidences.append(float(score))
        elif isinstance(page_raw, (list, tuple)):
            for line in page_raw:
                result = self._parse_ocr_line(line)
                if result is not None:
                    text, confidence, bbox = result
                    blocks.append(OCRBlock(text=text, confidence=confidence, bbox=bbox))
                    confidences.append(confidence)

        text = "\n".join(block.text for block in blocks if block.text)
        average = sum(confidences) / len(confidences) if confidences else None
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


__all__ = ["PaddleOCREngine", "paddleocr_init_lock"]
