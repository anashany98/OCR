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

import os
import tempfile
import threading
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
import sys

from app.ocr.base import OCRBlock, OCRResult
from app.ocr.preprocess import preprocess_for_paddle
from app.services.metrics import track_ocr_duration


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


class PaddleOCREngine:
    """PaddleOCR 3.x engine. Implements the :class:`BaseOCREngine` protocol."""

    name: str = "paddleocr"

    @cached_property
    def _engine(self):
        result = [None]
        error = [None]

        def _init_engine():
            try:
                with paddleocr_init_lock():
                    from paddleocr import PaddleOCR
                    result[0] = PaddleOCR(
                        use_angle_cls=True,
                        lang="es",
                        enable_mkldnn=False,
                    )
            except Exception as e:
                error[0] = e

        t = threading.Thread(target=_init_engine, daemon=True)
        t.start()
        t.join(timeout=120)

        if t.is_alive():
            raise TimeoutError("PaddleOCR initialization timed out after 120s")
        if error[0] is not None:
            raise error[0]
        return result[0]

    def extract(self, image_path: Path) -> OCRResult:
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
                        bbox = _polygon_to_bbox(poly.tolist() if hasattr(poly, 'tolist') else poly)

                    blocks.append(OCRBlock(
                        text=text or "",
                        confidence=float(score) if score is not None else None,
                        bbox=bbox,
                    ))
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

    def _parse_ocr_line(self, line: object) -> tuple[str, float, tuple[float, float, float, float] | None] | None:
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
    if not isinstance(polygon, (list, tuple)):
        return None
    try:
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
        return min(xs), min(ys), max(xs), max(ys)
    except (IndexError, TypeError, ValueError):
        return None


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
