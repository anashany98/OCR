"""Document parsers.

Each parser takes a file path and returns an :class:`ExtractedDocument`
with one or more pages of plain text plus optional bounding-box blocks.
The output is consumed by the OCR pipeline and by the AI agent.
"""

from __future__ import annotations

from pathlib import Path

from app.ocr.base import BaseOCREngine
from app.parsers.types import ExtractedDocument


def parse_excel(path: Path) -> ExtractedDocument:
    from app.parsers.excel import parse_excel as _impl

    return _impl(path)


def parse_msg(path: Path) -> ExtractedDocument:
    from app.parsers.msg import parse_msg as _impl

    return _impl(path)


def parse_pdf(path: Path, output_dir: Path, ocr_engine: BaseOCREngine) -> ExtractedDocument:
    from app.parsers.pdf import parse_pdf as _impl

    return _impl(path, output_dir, ocr_engine)


def parse_image(path: Path, output_dir: Path, ocr_engine: BaseOCREngine) -> ExtractedDocument:
    from app.parsers.image import parse_image as _impl

    return _impl(path, output_dir, ocr_engine)


def parse_csv_or_text(path: Path) -> ExtractedDocument:
    from app.parsers.text_like import parse_csv_or_text as _impl

    return _impl(path)
