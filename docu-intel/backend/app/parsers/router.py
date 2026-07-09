from __future__ import annotations

import logging
from pathlib import Path

from app.ocr.base import BaseOCREngine
from app.parsers.content_router import classify_content

logger = logging.getLogger("app.parsers.router")
from app.parsers.doc import parse_doc
from app.parsers.docx import parse_docx
from app.parsers.dxf import parse_dxf
from app.parsers.excel import parse_excel
from app.parsers.image import parse_image
from app.parsers.msg import parse_msg
from app.parsers.pdf import parse_pdf
from app.parsers.plain import parse_plain_text
from app.parsers.types import ExtractedDocument

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}
TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".log", ".eml"}
MSG_EXTENSIONS = {".msg"}
DXF_EXTENSIONS = {".dxf"}


def parse_document(
    path: Path,
    output_dir: Path,
    ocr_engine: BaseOCREngine,
    folder_hint: str | None = None,
) -> ExtractedDocument:
    extension = path.suffix.lower()

    # Content-aware routing for images: classify before OCR
    if extension in IMAGE_EXTENSIONS:
        classification = classify_content(path, folder_hint=folder_hint)
        content_route = classification.route.value if classification.route else None
        logger.info(
            "Content router: %s -> %s (confidence=%.2f, reason=%s)",
            path.name,
            classification.route.value,
            classification.confidence,
            classification.reason,
        )
        return parse_image(path, output_dir, ocr_engine, content_route=content_route)

    if extension == ".pdf":
        return parse_pdf(path, output_dir, ocr_engine, folder_hint=folder_hint)
    if extension in EXCEL_EXTENSIONS:
        return parse_excel(path)
    if extension == ".docx":
        return parse_docx(path)
    if extension == ".doc":
        return parse_doc(path)
    if extension in MSG_EXTENSIONS:
        return parse_msg(path)
    if extension in DXF_EXTENSIONS:
        return parse_dxf(path, output_dir)
    if extension in TEXT_EXTENSIONS:
        return parse_plain_text(path)
    return parse_plain_text(path)
