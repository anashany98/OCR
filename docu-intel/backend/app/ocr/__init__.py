"""OCR engines.

This package groups every OCR backend (Tesseract, PaddleOCR,
PaddleX / PP-Structure, dots.mocr) behind a common ``BaseOCREngine``
contract. The adapters under :mod:`app.ocr.adapter` hide PaddleOCR /
PaddleX version drift from the rest of the code.
"""

from app.ocr.adapter import (
    PaddleOCRAdapter,
    StructureAdapter,
    normalize_paddle_output,
    normalize_structure_output,
    paddleocr_init_lock,
    polygon_to_bbox,
)
from app.ocr.base import BaseOCREngine, OCRBlock, OCRResult
from app.ocr.cascading import CascadingOCREngine
from app.ocr.dots_mocr import DotsMOCRConfig, DotsMOCREngine
from app.ocr.factory import (
    clear_ocr_engine_cache,
    get_ocr_engine,
    get_ocr_engine_class,
    preload_ocr_engine,
)
from app.ocr.model_registry import (
    OcrProfile,
    StructureProfile,
    get_ocr_profile,
    get_structure_profile,
    list_ocr_profiles,
    list_structure_profiles,
    resolve_ocr_models,
    resolve_structure_pipeline,
)
from app.ocr.paddle import PaddleOCREngine
from app.ocr.pp_structure import PPStructureEngine
from app.ocr.tesseract import TesseractOCREngine


__all__ = [
    # Base
    "BaseOCREngine",
    "OCRBlock",
    "OCRResult",
    # Adapters (UPG-3 / UPG-4)
    "PaddleOCRAdapter",
    "StructureAdapter",
    "normalize_paddle_output",
    "normalize_structure_output",
    "paddleocr_init_lock",
    "polygon_to_bbox",
    # Registry (UPG-2)
    "OcrProfile",
    "StructureProfile",
    "get_ocr_profile",
    "get_structure_profile",
    "list_ocr_profiles",
    "list_structure_profiles",
    "resolve_ocr_models",
    "resolve_structure_pipeline",
    # Engines (legacy surface kept stable)
    "TesseractOCREngine",
    "PaddleOCREngine",
    "PPStructureEngine",
    "CascadingOCREngine",
    "DotsMOCREngine",
    "DotsMOCRConfig",
    # Factory
    "get_ocr_engine",
    "get_ocr_engine_class",
    "preload_ocr_engine",
    "clear_ocr_engine_cache",
]