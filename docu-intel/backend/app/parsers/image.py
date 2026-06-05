from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.ocr.base import BaseOCREngine
from app.ocr.preprocess import preprocess_for_ocr
from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage


def parse_image(path: Path, output_dir: Path, ocr_engine: BaseOCREngine) -> ExtractedDocument:
    from PIL import Image

    with Image.open(path) as image:
        width, height = image.size
    megapixels = (width * height) / 1_000_000
    if megapixels > settings.max_image_megapixels:
        raise ValueError(f"max_image_megapixels exceeded: {megapixels:.2f} > {settings.max_image_megapixels}")

    ocr_path = preprocess_for_ocr(path)
    result = ocr_engine.extract(ocr_path)
    # ``result.engine`` reports which engine actually produced the
    # text (the cascade's primary or fallback). Fall back to the
    # engine's static name for engines that don't set the field.
    actual_engine = result.engine or ocr_engine.name
    blocks = [
        ExtractedBlock(
            block_type="text",
            text=block.text,
            page_number=1,
            bbox=block.bbox,
            confidence=block.confidence,
            source_engine=actual_engine,
        )
        for block in result.blocks
    ]
    page = ExtractedPage(
        page_number=1,
        width=float(width),
        height=float(height),
        text=result.text,
        image_path=str(path),
        ocr_confidence=result.confidence,
        ocr_engine=actual_engine,
        blocks=blocks,
    )

    # On-demand vision fallback: if OCR (cascading tesseract+paddle) couldn't
    # extract enough text, ask the vision model to transcribe the image.
    # The vision model is loaded just for this call and then scheduled to
    # unload.
    if (
        settings.vision_table_transcription
        and settings.vision_model
        and (not result.text or len(result.text.strip()) < 30 or (result.confidence or 0) < 0.4)
    ):
        try:
            from app.services.vision_manager import VisionManager
            from app.ai.local_client import LocalVisionClient
            import asyncio
            VisionManager.cancel_pending_unload()
            if not VisionManager.is_loaded():
                VisionManager.ensure_loaded()
            client = LocalVisionClient()
            loop = asyncio.new_event_loop()
            try:
                vision_text = loop.run_until_complete(
                    client.transcribe_table(path)
                )
            finally:
                loop.close()
            if vision_text:
                # Append the vision transcription as an extra block so
                # the LLM and the frontend can use it.
                page.blocks.append(
                    ExtractedBlock(
                        block_type="table",
                        text=vision_text,
                        page_number=1,
                        bbox=(0.0, 0.0, float(width), float(height)),
                        confidence=0.85,
                        source_engine="vision",
                    )
                )
                # If the OCR text is empty, replace the page text with
                # the vision transcription so downstream stages see it.
                if not result.text or len(result.text.strip()) < 30:
                    page.text = vision_text
                    page.ocr_engine = "vision"
                    page.ocr_confidence = 0.85
            VisionManager.schedule_unload()
        except Exception:
            # Vision fallback is best-effort; the OCR result still stands.
            pass

    return ExtractedDocument(pages=[page])
