from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from contextlib import contextmanager, nullcontext
import tempfile


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

            return PaddleOCR(use_angle_cls=True, lang="es", show_log=False)

    def extract(self, image_path: Path) -> OCRResult:
        raw = self._engine.ocr(str(image_path), cls=True)
        blocks: list[OCRBlock] = []
        confidences: list[float] = []

        for page in raw or []:
            for line in page or []:
                if len(line) < 2:
                    continue
                polygon, payload = line
                text, confidence = payload[0], float(payload[1])
                bbox = _polygon_to_bbox(polygon)
                blocks.append(OCRBlock(text=text, confidence=confidence, bbox=bbox))
                confidences.append(confidence)

        text = "\n".join(block.text for block in blocks if block.text)
        average = sum(confidences) / len(confidences) if confidences else None
        return OCRResult(text=text, confidence=average, blocks=blocks)


def _polygon_to_bbox(polygon) -> tuple[float, float, float, float] | None:
    try:
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
        return min(xs), min(ys), max(xs), max(ys)
    except Exception:
        return None


@contextmanager
def paddleocr_init_lock():
    try:
        import fcntl
    except Exception:
        with nullcontext():
            yield
        return

    lock_path = Path(tempfile.gettempdir()) / "docuintel_paddleocr_init.lock"
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
