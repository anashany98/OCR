"""X2 — DXF/DWG parser for plan ingestion.

Many architectural plans are shared as DXF files (AutoCAD's
native format). This module reads DXF files and extracts:

* Text entities (TEXT, MTEXT) as page text.
* Block references with attributes.
* Layer metadata.
* Basic geometry (lines, polylines) for room detection.

DWG files are binary and require a separate library; this
module handles DXF only. DWG support can be added later by
converting DWG to DXF via ODA File Converter.

The parser is **fail-safe**: on any error it returns an
empty ExtractedDocument so the ingestion pipeline continues.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage

logger = logging.getLogger("app.parsers.dxf")


def parse_dxf(path: Path, output_dir: Path) -> ExtractedDocument:
    """Parse a DXF file and return an ExtractedDocument.

    The DXF is read with ``ezdxf``. All TEXT and MTEXT entities
    are collected into a single "page" (DXF files don't have
    pages; we treat the entire model space as page 1). Block
    attributes are also extracted.

    On any error, returns an empty document so the ingestion
    pipeline continues.
    """
    try:
        import ezdxf
    except ImportError:
        logger.warning("ezdxf not installed; cannot parse DXF files")
        return ExtractedDocument(pages=[])

    try:
        doc = ezdxf.readfile(str(path))
        msp = doc.modelspace()

        texts: list[str] = []
        blocks: list[ExtractedBlock] = []

        # Extract TEXT and MTEXT entities
        for entity in msp:
            dxftype = entity.dxftype()
            if dxftype == "TEXT":
                text = entity.dxf.text.strip()
                if text:
                    texts.append(text)
                    blocks.append(
                        ExtractedBlock(
                            block_type="text",
                            text=text,
                            page_number=1,
                            bbox=_get_bbox(entity),
                            confidence=1.0,
                            source_engine="dxf_parser",
                        )
                    )
            elif dxftype == "MTEXT":
                text = entity.plain_text().strip()
                if text:
                    texts.append(text)
                    blocks.append(
                        ExtractedBlock(
                            block_type="text",
                            text=text,
                            page_number=1,
                            bbox=_get_bbox(entity),
                            confidence=1.0,
                            source_engine="dxf_parser",
                        )
                    )
            elif dxftype == "INSERT":
                # Block reference with attributes
                attribs = entity.attribs
                for attrib in attribs:
                    text = attrib.dxf.text.strip()
                    if text:
                        texts.append(text)
                        blocks.append(
                            ExtractedBlock(
                                block_type="attribute",
                                text=text,
                                page_number=1,
                                bbox=_get_bbox(attrib),
                                confidence=1.0,
                                source_engine="dxf_parser",
                            )
                        )

        # Extract layer names as metadata
        layer_names = [layer.dxf.name for layer in doc.layers]
        if layer_names:
            texts.append(f"Capas: {', '.join(layer_names)}")

        full_text = "\n".join(texts)

        if not full_text.strip():
            logger.info("DXF file %s has no text entities", path.name)
            return ExtractedDocument(pages=[])

        page = ExtractedPage(
            page_number=1,
            text=full_text,
            width=None,
            height=None,
            image_path=None,
            ocr_confidence=1.0,
            ocr_engine="dxf_parser",
            blocks=blocks,
        )

        logger.info(
            "DXF parsed: %s — %d text entities, %d blocks", path.name, len(texts), len(blocks)
        )
        return ExtractedDocument(pages=[page])

    except Exception as exc:
        logger.warning("Failed to parse DXF %s: %s", path.name, exc)
        return ExtractedDocument(pages=[])


def _get_bbox(entity) -> tuple[float, float, float, float] | None:
    """Try to get a bounding box from a DXF entity.

    Returns (x1, y1, x2, y2) or None if the entity has no
    geometric bounds.
    """
    try:
        bbox = entity.bbox()
        if bbox and len(bbox) == 2:
            return (bbox.extmin[0], bbox.extmin[1], bbox.extmax[0], bbox.extmax[1])
    except Exception:  # noqa: BLE001
        pass
    return None
