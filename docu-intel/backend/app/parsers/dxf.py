"""X2 — DXF/DWG parser for plan ingestion.

Many architectural plans are shared as DXF files (AutoCAD's
native format). This module reads DXF files and extracts:

* Text entities (TEXT, MTEXT) as page text.
* DIMENSION entities with real measurement values.
* Block references (INSERT) with attributes.
* Layer metadata.
* Geometry (LINE, LWPOLYLINE, ARC) for room detection.
* Units from $INSUNITS header variable.

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

# $INSUNITS values → human-readable unit names
_INSUNITS_MAP = {
    0: "unitless",
    1: "inches",
    2: "feet",
    3: "miles",
    4: "mm",
    5: "cm",
    6: "m",
    7: "km",
    8: "microinches",
    9: "mils",
    10: "yards",
    11: "angstroms",
    12: "nanometers",
    13: "microns",
    14: "dm",
    15: "dam",
    16: "nm",
    17: "pm",
}


def parse_dxf(path: Path, output_dir: Path) -> ExtractedDocument:
    """Parse a DXF file and return an ExtractedDocument.

    Extracts TEXT, MTEXT, DIMENSION, INSERT entities, geometry,
    and units. Everything goes into a single "page" (DXF files
    don't have pages; model space = page 1).

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
    except Exception as exc:
        logger.warning("Failed to read DXF %s: %s", path.name, exc)
        return ExtractedDocument(pages=[])

    try:
        return _extract_dxf(doc, path)
    except Exception as exc:
        logger.warning("Failed to parse DXF %s: %s", path.name, exc)
        return ExtractedDocument(pages=[])


def _extract_dxf(doc, path: Path) -> ExtractedDocument:
    msp = doc.modelspace()

    # Read units from header
    units_code = 0
    try:
        if "$INSUNITS" in doc.header:
            units_code = int(doc.header["$INSUNITS"])
    except (ValueError, TypeError):
        pass
    unit_name = _INSUNITS_MAP.get(units_code, f"unknown({units_code})")

    texts: list[str] = []
    blocks: list[ExtractedBlock] = []
    dimensions: list[dict] = []
    geometry: list[dict] = []
    inserts: list[dict] = []

    for entity in msp:
        dxftype = entity.dxftype()
        layer = entity.dxf.layer if hasattr(entity.dxf, "layer") else "0"

        if dxftype in ("TEXT", "MTEXT"):
            text = _extract_text(entity)
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

        elif dxftype == "DIMENSION":
            dim = _extract_dimension(entity)
            if dim is not None:
                dimensions.append(dim)
                texts.append(f"Cota: {dim['display_value']}")
                blocks.append(
                    ExtractedBlock(
                        block_type="dimension",
                        text=dim["display_value"],
                        page_number=1,
                        bbox=_get_bbox(entity),
                        confidence=0.95,
                        source_engine="dxf_parser",
                    )
                )

        elif dxftype == "INSERT":
            name = entity.dxf.name if hasattr(entity.dxf, "name") else ""
            x = entity.dxf.insert.x if hasattr(entity.dxf, "insert") else 0
            y = entity.dxf.insert.y if hasattr(entity.dxf, "insert") else 0
            inserts.append({"name": name, "x": float(x), "y": float(y), "layer": layer})

            # Extract block attributes
            for attrib in entity.attribs:
                text = attrib.dxf.text.strip()
                if text:
                    texts.append(text)
                    blocks.append(
                        ExtractedBlock(
                            block_type="text",
                            text=text,
                            page_number=1,
                            bbox=_get_bbox(attrib),
                            confidence=1.0,
                            source_engine="dxf_parser",
                        )
                    )

        elif dxftype in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC"):
            geom = _extract_geometry(entity)
            if geom is not None:
                geometry.append(geom)

    # Layer names
    layer_names = sorted({layer.dxf.name for layer in doc.layers})
    if layer_names:
        texts.append(f"Capas: {', '.join(layer_names)}")

    # Units
    if unit_name != "unitless":
        texts.append(f"Unidades: {unit_name}")

    # Geometry summary
    if geometry:
        counts = {}
        for g in geometry:
            counts[g["type"]] = counts.get(g["type"], 0) + 1
        geom_summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        texts.append(f"Geometría: {geom_summary}")

    # Dimension summary
    if dimensions:
        texts.append(f"Cotas DIMENSION: {len(dimensions)}")

    # Insert summary
    if inserts:
        block_counts = {}
        for ins in inserts:
            block_counts[ins["name"]] = block_counts.get(ins["name"], 0) + 1
        insert_summary = ", ".join(f"{k}={v}" for k, v in sorted(block_counts.items()))
        texts.append(f"Bloques: {insert_summary}")

    full_text = "\n".join(texts)

    if not full_text.strip():
        logger.info("DXF file %s has no extractable content", path.name)
        return ExtractedDocument(pages=[])

    page = ExtractedPage(
        page_number=1,
        text=full_text,
        width=None,
        height=None,
        image_path=None,
        ocr_confidence=None,
        ocr_content_kind="native_text",
        ocr_engine="dxf_parser",
        blocks=blocks,
    )

    logger.info(
        "DXF parsed: %s — %d texts, %d dims, %d geom, %d inserts, units=%s",
        path.name, len(texts), len(dimensions), len(geometry), len(inserts), unit_name,
    )
    return ExtractedDocument(pages=[page])


def _extract_text(entity) -> str:
    """Extract plain text from TEXT or MTEXT entity."""
    try:
        if entity.dxftype() == "TEXT":
            return entity.dxf.text.strip()
        elif entity.dxftype() == "MTEXT":
            return entity.plain_text().strip()
    except Exception:
        pass
    return ""


def _extract_dimension(entity) -> dict | None:
    """Extract a DIMENSION entity's measurement value and position.

    Returns dict with keys: value, unit, display_value, x, y, layer.
    """
    try:
        measurement = entity.get_measurement()
        if measurement is None:
            return None
        value = float(measurement)

        # Try to get the defpoint (dimension line position)
        defpoint = getattr(entity.dxf, "defpoint", None)
        x = defpoint.x if defpoint else 0
        y = defpoint.y if defpoint else 0

        # Format display value
        display_value = f"{value:.2f}"

        return {
            "value": value,
            "unit": "mm",  # DXF default; overridden by $INSUNITS
            "display_value": display_value,
            "x": float(x),
            "y": float(y),
            "layer": entity.dxf.layer if hasattr(entity.dxf, "layer") else "0",
        }
    except Exception:
        return None


def _extract_geometry(entity) -> dict | None:
    """Extract geometry from LINE, LWPOLYLINE, POLYLINE, or ARC."""
    try:
        dxftype = entity.dxftype()
        layer = entity.dxf.layer if hasattr(entity.dxf, "layer") else "0"

        if dxftype == "LINE":
            start = entity.dxf.start
            end = entity.dxf.end
            return {
                "type": "line",
                "layer": layer,
                "start": (float(start.x), float(start.y)),
                "end": (float(end.x), float(end.y)),
            }

        elif dxftype == "LWPOLYLINE":
            points = [(float(p[0]), float(p[1])) for p in entity.get_points()]
            closed = entity.closed
            return {
                "type": "polyline",
                "layer": layer,
                "points": points,
                "closed": closed,
            }

        elif dxftype == "ARC":
            center = entity.dxf.center
            return {
                "type": "arc",
                "layer": layer,
                "center": (float(center.x), float(center.y)),
                "radius": float(entity.dxf.radius),
                "start_angle": float(entity.dxf.start_angle),
                "end_angle": float(entity.dxf.end_angle),
            }

    except Exception:
        pass
    return None


def _get_bbox(entity) -> tuple[float, float, float, float] | None:
    """Get bounding box from a DXF entity."""
    try:
        bbox = entity.bbox()
        if bbox and len(bbox) == 2:
            return (bbox.extmin[0], bbox.extmin[1], bbox.extmax[0], bbox.extmax[1])
    except Exception:  # noqa: BLE001
        pass
    return None
