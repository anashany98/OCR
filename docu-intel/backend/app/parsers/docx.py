"""Parser for .docx (OOXML) files — extracts text from the ZIP/XML archive.

Uses only stdlib (zipfile + xml.etree) — no external dependencies required.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage

DOCX_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def parse_docx(path: Path) -> ExtractedDocument:
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

    return ExtractedDocument(
        pages=[
            ExtractedPage(
                page_number=1,
                text=text,
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
    )
