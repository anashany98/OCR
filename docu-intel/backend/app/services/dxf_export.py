"""X3 — Export plan annotations to DXF format.

When a technician annotates rooms, dimensions and measurements
in the plan viewer, they should be able to export those
annotations as a DXF file that can be opened in AutoCAD / QGIS.

This module converts the ``PlanRoom.polygon_json`` and
``PlanDimension`` data into DXF entities (LWPOLYLINE for
rooms, LINE + TEXT for dimensions) on dedicated layers so the
export is clean and professional.

The module uses ``ezdxf`` (the same library as X2) and
requires no additional dependencies. The export is
**fail-safe**: on any error the function returns ``None`` and
logs the error.

The DXF output is a minimal valid DXF R2010 file that can be
opened by any CAD software.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.services.dxf_export")


def export_annotations_to_dxf(
    *,
    rooms: list[dict],
    dimensions: list[dict],
    output_path: str | Path,
    scale_ratio: float | None = None,
) -> Path | None:
    """Export plan annotations to a DXF file.

    Args:
        rooms: list of room dicts with at least ``name``,
            ``area_m2``, ``polygon`` (list of ``[x, y]``).
        dimensions: list of dimension dicts with at least
            ``raw_text``, ``value``, ``unit``, ``start``
            (``[x, y]``), ``end`` (``[x, y]``).
        output_path: where to write the ``.dxf`` file.
        scale_ratio: the plan's scale ratio (e.g. 100 for
            1:100). Used to convert m → mm for the DXF
            coordinate system.

    Returns:
        The ``Path`` to the written DXF file, or ``None`` on
        any error.
    """
    try:
        import ezdxf
    except ImportError:
        logger.debug("ezdxf not available, skipping DXF export")
        return None

    try:
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()

        # Create layers.
        doc.layers.add("habitaciones_ia", color=1)  # red
        doc.layers.add("cotas_ia", color=3)           # green
        doc.layers.add("texto_ia", color=7)            # white

        mm_per_m = 1000.0

        # Export rooms.
        for room in rooms:
            polygon = room.get("polygon")
            if not polygon or len(polygon) < 3:
                continue
            name = room.get("name", "")
            area = room.get("area_m2")
            points = [(p[0] * mm_per_m, p[1] * mm_per_m) for p in polygon]
            # Close the polygon if not already closed.
            if points[0] != points[-1]:
                points.append(points[0])
            msp.add_lwpolyline(
                points,
                dxfattribs={"layer": "habitaciones_ia"},
            )
            # Add room name at centroid.
            if name:
                cx = sum(p[0] for p in points[:-1]) / len(points[:-1])
                cy = sum(p[1] for p in points[:-1]) / len(points[:-1])
                label = f"{name}"
                if area is not None:
                    label += f" ({area:.1f} m²)"
                msp.add_text(
                    label,
                    dxfattribs={
                        "layer": "texto_ia",
                        "height": 200,  # mm
                        "insert": (cx, cy),
                    },
                )

        # Export dimensions.
        for dim in dimensions:
            start = dim.get("start")
            end = dim.get("end")
            if not start or not end:
                continue
            raw_text = dim.get("raw_text", "")
            value = dim.get("value")
            unit = dim.get("unit", "mm")
            p1 = (start[0] * mm_per_m, start[1] * mm_per_m)
            p2 = (end[0] * mm_per_m, end[1] * mm_per_m)
            msp.add_line(
                p1, p2,
                dxfattribs={"layer": "cotas_ia"},
            )
            # Add dimension text at midpoint.
            mx = (p1[0] + p2[0]) / 2
            my = (p1[1] + p2[1]) / 2
            label = raw_text or f"{value} {unit}"
            msp.add_text(
                label,
                dxfattribs={
                    "layer": "texto_ia",
                    "height": 150,
                    "insert": (mx, my),
                },
            )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(str(output_path))
        return output_path

    except Exception as exc:
        logger.warning("DXF export failed: %s", exc)
        return None


__all__ = [
    "export_annotations_to_dxf",
]
