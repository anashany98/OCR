from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.ocr.paddle import PaddleOCREngine
from app.ocr.preprocess import preprocess_for_ocr
from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage


def parse_image(path: Path, ocr_engine: PaddleOCREngine) -> ExtractedDocument:
    from PIL import Image

    with Image.open(path) as image:
        width, height = image.size
    megapixels = (width * height) / 1_000_000
    if megapixels > settings.max_image_megapixels:
        raise ValueError(f"max_image_megapixels exceeded: {megapixels:.2f} > {settings.max_image_megapixels}")

    ocr_path = preprocess_for_ocr(path)
    result = ocr_engine.extract(ocr_path)
    blocks = [
        ExtractedBlock(
            block_type="text",
            text=block.text,
            page_number=1,
            bbox=block.bbox,
            confidence=block.confidence,
            source_engine="paddleocr",
        )
        for block in result.blocks
    ]
    return ExtractedDocument(
        pages=[
            ExtractedPage(
                page_number=1,
                width=float(width),
                height=float(height),
                text=result.text,
                image_path=str(path),
                ocr_confidence=result.confidence,
                blocks=blocks,
            )
        ]
    )
