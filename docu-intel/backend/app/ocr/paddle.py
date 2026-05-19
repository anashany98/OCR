from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from contextlib import contextmanager, nullcontext
import tempfile
import sys


@dataclass
class OCRBlock:
    text: str
    confidence: float | None
    bbox: tuple[float, float, float, float] | None


@dataclass
class OCRResult:
    text: str
    confidence: float | None
    blocks: list[OCRBlock]


class PaddleOCREngine:
    @cached_property
    def _engine(self):
        with paddleocr_init_lock():
            from paddleocr import PaddleOCR

            return PaddleOCR(use_angle_cls=True, lang="es")

    def extract(self, image_path: Path) -> OCRResult:
        raw = self._engine.ocr(str(image_path), cls=True)
        blocks: list[OCRBlock] = []
        confidences: list[float] = []

        if raw is None:
            return OCRResult(text="", confidence=None, blocks=[])

        if not isinstance(raw, (list, tuple)):
            raw = [raw]

        for page in raw:
            if page is None:
                continue
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
        return OCRResult(text=text, confidence=average, blocks=blocks)

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