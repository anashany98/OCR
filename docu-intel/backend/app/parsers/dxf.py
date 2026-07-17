"""X2 — DXF/DWG parser for plan ingestion.

Many architectural plans are shared as DXF files (AutoCAD's
native format). This module reads DXF files and extracts:

* Text entities (TEXT, MTEXT) as page text.
* DIMENSION entities with real measurement values.
* Block references (INSERT) with attributes.
* Layer metadata.
* Geometry (LINE, LWPOLYLINE, POLYLINE, ARC, CIRCLE) for room detection.
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

from app.parsers.types import (
    CadDimensionEntity,
    CadExtraction,
    CadGeometryEntity,
    CadInsertEntity,
    CadMetadata,
    CadTextEntity,
    ExtractedBlock,
    ExtractedDocument,
    ExtractedPage,
)

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
    cad_texts: list[CadTextEntity] = []
    cad_dimensions: list[CadDimensionEntity] = []
    cad_geometry: list[CadGeometryEntity] = []
    cad_inserts: list[CadInsertEntity] = []

    for entity in msp:
        dxftype = entity.dxftype()
        layer = entity.dxf.layer if hasattr(entity.dxf, "layer") else "0"

        if dxftype in ("TEXT", "MTEXT"):
            text = _extract_text(entity)
            if text:
                insertion = _entity_insert_point(entity)
                texts.append(text)
                cad_texts.append(
                    CadTextEntity(
                        entity_handle=_entity_handle(entity),
                        text=text,
                        layer=layer,
                        insertion_point=insertion,
                    )
                )
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
            dim = _extract_dimension(entity, unit_name)
            if dim is not None:
                dimensions.append(dim)
                texts.append(f"Cota: {dim['display_value']}")
                cad_dimensions.append(
                    CadDimensionEntity(
                        entity_handle=_entity_handle(entity),
                        layer=layer,
                        value=dim["value"],
                        displayed_text=dim["display_value"],
                        native_unit=dim["unit"],
                        unit_source=dim["unit_source"],
                        normalized_value_m=dim["value_m"],
                        definition_points=tuple(dim["definition_points"]),
                        text_point=dim["text_point"],
                        confidence=0.95,
                    )
                )
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
            attributes: dict[str, str] = {}
            inserts.append({"name": name, "x": float(x), "y": float(y), "layer": layer})

            # Extract block attributes
            for attrib in entity.attribs:
                text = attrib.dxf.text.strip()
                if text:
                    attributes[str(getattr(attrib.dxf, "tag", "") or "")] = text
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
            cad_inserts.append(
                CadInsertEntity(
                    entity_handle=_entity_handle(entity),
                    block_name=str(name),
                    layer=layer,
                    insertion_point=(float(x), float(y)),
                    attributes=attributes,
                    rotation=float(getattr(entity.dxf, "rotation", 0.0) or 0.0),
                    scale=tuple(
                        float(getattr(entity.dxf, axis, 1.0) or 1.0)
                        for axis in ("xscale", "yscale", "zscale")
                    ),
                )
            )

        elif dxftype in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE"):
            geom = _extract_geometry(entity)
            if geom is not None:
                geometry.append(geom)
                cad_geometry.append(
                    CadGeometryEntity(
                        entity_handle=_entity_handle(entity),
                        entity_type=str(geom["type"]),
                        layer=layer,
                        geometry=geom,
                        closed=bool(geom.get("closed", False)),
                    )
                )

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
        path.name,
        len(texts),
        len(dimensions),
        len(geometry),
        len(inserts),
        unit_name,
    )
    cad = CadExtraction(
        metadata=CadMetadata(
            source_format=path.suffix.lower().lstrip(".") or "dxf",
            unit=unit_name if unit_name != "unitless" else None,
            unit_code=units_code,
            layers=tuple(layer_names),
            extents=_drawing_extents(cad_geometry),
            dxf_version=str(getattr(doc, "dxfversion", "") or "") or None,
        ),
        dimensions=tuple(cad_dimensions),
        geometry=tuple(cad_geometry),
        inserts=tuple(cad_inserts),
        texts=tuple(cad_texts),
    )
    return ExtractedDocument(pages=[page], cad=cad)


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


def _extract_dimension(entity, drawing_unit: str) -> dict | None:
    """Extract a DIMENSION entity's measurement value and position.

    Returns dict with keys: value, unit, display_value, x, y, layer.
    """
    try:
        measurement = entity.get_measurement()
        if measurement is None:
            return None
        value = float(measurement)

        definition_points = _dimension_points(entity)
        text_point = _point_from_value(getattr(entity.dxf, "text_midpoint", None))

        text_override = str(getattr(entity.dxf, "text", "") or "").strip()
        display_value = text_override if text_override and text_override != "<>" else f"{value:.2f}"
        unit = drawing_unit if drawing_unit and drawing_unit != "unitless" else None

        return {
            "value": value,
            "unit": unit,
            "unit_source": "$INSUNITS" if unit else "unknown",
            "display_value": display_value,
            "value_m": _to_metres(value, unit),
            "definition_points": definition_points,
            "text_point": text_point,
            "layer": entity.dxf.layer if hasattr(entity.dxf, "layer") else "0",
        }
    except Exception:
        return None


def _extract_geometry(entity) -> dict | None:
    """Extract geometry from common native model-space entities."""
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

        elif dxftype == "POLYLINE":
            # Older DXF files use heavyweight POLYLINE/VERTEX records rather
            # than LWPOLYLINE. Keep them as native geometry instead of
            # silently advertising support while dropping their shape.
            points = [
                (float(vertex.dxf.location.x), float(vertex.dxf.location.y))
                for vertex in entity.vertices
            ]
            if len(points) < 2:
                return None
            return {
                "type": "polyline",
                "layer": layer,
                "points": points,
                "closed": bool(entity.is_closed),
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

        elif dxftype == "CIRCLE":
            center = entity.dxf.center
            return {
                "type": "circle",
                "layer": layer,
                "center": (float(center.x), float(center.y)),
                "radius": float(entity.dxf.radius),
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


def _entity_handle(entity) -> str | None:
    value = getattr(getattr(entity, "dxf", None), "handle", None)
    return str(value) if value else None


def _point_from_value(value) -> tuple[float, float] | None:
    if value is None:
        return None
    try:
        return float(value.x), float(value.y)
    except (AttributeError, TypeError, ValueError):
        return None


def _entity_insert_point(entity) -> tuple[float, float] | None:
    return _point_from_value(getattr(getattr(entity, "dxf", None), "insert", None))


def _dimension_points(entity) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for attr in ("defpoint", "defpoint2", "defpoint3", "defpoint4"):
        point = _point_from_value(getattr(entity.dxf, attr, None))
        if point is not None and point not in points:
            points.append(point)
    return points


def _to_metres(value: float, unit: str | None) -> float | None:
    factors = {
        "mm": 0.001,
        "cm": 0.01,
        "m": 1.0,
        "km": 1000.0,
        "inches": 0.0254,
        "feet": 0.3048,
        "yards": 0.9144,
    }
    factor = factors.get((unit or "").lower())
    return value * factor if factor is not None else None


def _drawing_extents(geometry: list[CadGeometryEntity]) -> tuple[float, float, float, float] | None:
    points: list[tuple[float, float]] = []
    for item in geometry:
        payload = item.geometry
        if payload.get("type") == "line":
            points.extend((tuple(payload["start"]), tuple(payload["end"])))
        elif payload.get("type") == "polyline":
            points.extend(tuple(point) for point in payload.get("points", ()))
        elif payload.get("type") == "arc" or payload.get("type") == "circle":
            center = payload.get("center")
            radius = payload.get("radius")
            if center and radius is not None:
                x, y = center
                points.extend(((x - radius, y - radius), (x + radius, y + radius)))
    if not points:
        return None
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )
