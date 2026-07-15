"""Parser for .docx (OOXML) files — extracts text from the ZIP/XML archive.

Uses only stdlib (zipfile + xml.etree) — no external dependencies required.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from app.ocr.base import BaseOCREngine
from app.parsers.embedded_images import EmbeddedImage, extract_embedded_image_pages
from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage

DOCX_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _embedded_images(path: Path) -> list[EmbeddedImage]:
    with zipfile.ZipFile(path, "r") as archive:
        return [
            EmbeddedImage(filename=Path(name).name, content=archive.read(name))
            for name in archive.namelist()
            if name.startswith("word/media/") and not name.endswith("/")
        ]


def parse_docx(
    path: Path,
    output_dir: Path | None = None,
    ocr_engine: BaseOCREngine | None = None,
) -> ExtractedDocument:
    """Extract text from a .docx file (ZIP archive of XML)."""
    paragraphs: list[str] = []

    with zipfile.ZipFile(path, "r") as archive:
        if "word/document.xml" not in archive.namelist():
            raise ValueError("Not a valid .docx file: word/document.xml not found")

        tree = ET.parse(archive.open("word/document.xml"))
        root = tree.getroot()

        for paragraph in root.iter(f"{{{DOCX_NAMESPACE}}}p"):
            texts: list[str] = []
            for run in paragraph.iter(f"{{{DOCX_NAMESPACE}}}t"):
                if run.text:
                    texts.append(run.text)
            if texts:
                paragraphs.append("".join(texts))

    text = "\n".join(paragraphs)
    if not text.strip():
        text = "(documento sin texto extraíble)"

    pages = [
        ExtractedPage(
            page_number=1,
            text=text,
            ocr_content_kind="native_text",
            blocks=[
                ExtractedBlock(
                    block_type="text",
                    text=text,
                    page_number=1,
                    confidence=0.95,
                    source_engine="docx_parser",
                )
            ],
        )
    ]
    pages.extend(
        extract_embedded_image_pages(
            _embedded_images(path),
            output_dir=output_dir,
            ocr_engine=ocr_engine,
            first_page_number=len(pages) + 1,
        )
    )
    return ExtractedDocument(pages=pages)
