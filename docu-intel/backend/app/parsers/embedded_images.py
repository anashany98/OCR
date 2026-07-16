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
from app.services.ocr_page_roles import is_probably_decorative_embedded_media

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

    accepted_images = 0
    for image in images:
        suffix = Path(image.filename).suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            logger.info("Skipping embedded non-image attachment: %s", image.filename)
            continue
        if not image.content or len(image.content) > settings.max_embedded_image_bytes:
            logger.warning("Skipping embedded image outside byte limit: %s", image.filename)
            continue
        if accepted_images >= settings.max_embedded_images_per_document:
            logger.warning("Embedded image limit reached; remaining images skipped")
            break
        accepted_images += 1

        digest = hashlib.sha256(image.content).hexdigest()[:16]
        stored_image = media_dir / f"embedded_{accepted_images}_{digest}{suffix}"
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
        # Mail/Office files often carry logos, social icons and signatures as
        # inline images.  Preserve their text for retrieval, but make their
        # confidence non-applicable so they never become false low-OCR work.
        if is_probably_decorative_embedded_media(
            image_path=str(stored_image),
            text=page.text,
        ):
            page.ocr_content_kind = "decorative"
            page.ocr_confidence = None
            page.ocr_engine = "decorative_media"
        for block in page.blocks:
            block.page_number = page_number
        extracted.append(page)
    return extracted
