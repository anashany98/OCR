"""Shared, bounded OCR for images embedded in digital documents."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.ocr.base import BaseOCREngine
from app.parsers.image import parse_image
from app.parsers.types import ExtractedDocument, ExtractedPage

logger = logging.getLogger("app.parsers.embedded_images")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


@dataclass(frozen=True)
class EmbeddedImage:
    filename: str
    content: bytes


def extract_embedded_image_pages(
    images: Iterable[EmbeddedImage],
    *,
    output_dir: Path | None,
    ocr_engine: BaseOCREngine | None,
    first_page_number: int,
) -> list[ExtractedPage]:
    """OCR embedded image payloads without turning decorative media into errors.

    The original Office/email archive is never changed. Images are copied to a
    document-owned output directory only when the caller supplied one; failed
    image OCR is logged and skipped so a logo or a corrupt attachment cannot
    turn a text document into ``needs_review`` by itself.
    """
    if output_dir is None or ocr_engine is None:
        return []

    extracted: list[ExtractedPage] = []
    media_dir = output_dir / "embedded"
    media_dir.mkdir(parents=True, exist_ok=True)

    for index, image in enumerate(images):
        if index >= settings.max_embedded_images_per_document:
            logger.warning("Embedded image limit reached; remaining images skipped")
            break
        suffix = Path(image.filename).suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            logger.info("Skipping embedded non-image attachment: %s", image.filename)
            continue
        if not image.content or len(image.content) > settings.max_embedded_image_bytes:
            logger.warning("Skipping embedded image outside byte limit: %s", image.filename)
            continue

        digest = hashlib.sha256(image.content).hexdigest()[:16]
        stored_image = media_dir / f"embedded_{index + 1}_{digest}{suffix}"
        stored_image.write_bytes(image.content)
        try:
            document: ExtractedDocument = parse_image(stored_image, media_dir, ocr_engine)
        except Exception as exc:
            logger.warning("Embedded image OCR failed for %s: %s", image.filename, type(exc).__name__)
            continue
        if not document.pages or not document.text.strip():
            continue

        page = document.pages[0]
        page_number = first_page_number + len(extracted)
        page.page_number = page_number
        page.text = f"[Imagen incrustada: {image.filename}]\n{page.text}"
        for block in page.blocks:
            block.page_number = page_number
        extracted.append(page)
    return extracted
