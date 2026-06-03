from __future__ import annotations

from pathlib import Path

from app.ocr.paddle import PaddleOCREngine
from app.parsers.doc import parse_doc
from app.parsers.docx import parse_docx
from app.parsers.excel import parse_excel
from app.parsers.image import parse_image
from app.parsers.pdf import parse_pdf
from app.parsers.plain import parse_plain_text
from app.parsers.types import ExtractedDocument

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}
TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".log", ".eml"}


def parse_document(path: Path, output_dir: Path, ocr_engine: PaddleOCREngine) -> ExtractedDocument:
    extension = path.suffix.lower()
    if extension == ".pdf":
        return parse_pdf(path, output_dir, ocr_engine)
    if extension in IMAGE_EXTENSIONS:
        return parse_image(path, ocr_engine)
    if extension in EXCEL_EXTENSIONS:
        return parse_excel(path)
    if extension == ".docx":
        return parse_docx(path)
    if extension == ".doc":
        return parse_doc(path)
    if extension in TEXT_EXTENSIONS:
        return parse_plain_text(path)
    return parse_plain_text(path)
