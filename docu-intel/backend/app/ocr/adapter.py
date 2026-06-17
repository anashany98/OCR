"""OCR engine package.

Public re-exports for adapters / registry / engines so that callers can
write ``from app.ocr.adapter import PaddleOCRAdapter, StructureAdapter``
and tests can stub the package-level name instead of the underlying
module path.
"""

from __future__ import annotations

from app.ocr.paddle_adapter import (
    PaddleOCRAdapter,
    normalize_paddle_output,
    paddleocr_init_lock,
    polygon_to_bbox,
)
from app.ocr.structure_adapter import StructureAdapter, normalize_structure_output


__all__ = [
    "PaddleOCRAdapter",
    "StructureAdapter",
    "normalize_paddle_output",
    "normalize_structure_output",
    "paddleocr_init_lock",
    "polygon_to_bbox",
]