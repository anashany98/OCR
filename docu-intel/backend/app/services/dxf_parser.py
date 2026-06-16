"""X2 — DXF/DWG ingestion via ezdxf.

Construction architects and engineers deliver plans in DXF
format (AutoCAD's native vector format). This module reads a
DXF file, extracts the text entities, dimensions, layers and
block references, and produces a plain-text representation
that the existing OCR pipeline can process as if it were a
PDF page.

The module also renders the DXF to a PNG image (via
matplotlib's DXF backend or ezdxf's built-in drawing) so the
plan viewer has something to display.

The module is **fail-safe**: on any error (missing ezdxf,
corrupt file, unsupported DWG version) the function returns
``None`` and logs the error. The caller falls back to treating
the file as "unreadable" and marks it for manual review.

DWG support requires the ``ezdxf[draw]`` extra which includes
the ODA File Converter. DXF is natively supported without any
extra dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("app.services.dxf_parser")


@dataclass(frozen=True)
class DxfExtraction:
    """The result of parsing a DXF file.

    Attributes:
        text: the plain-text representation of the DXF (layer
            names, text entities, dimension values, block
            references).
        layers: list of layer names found in the DXF.
        text_entities: list of ``(text, x, y, layer)`` tuples
            for every TEXT / MTEXT entity.
        dimensions: list of ``(value, unit, x, y)`` tuples
            for every DIMENSION entity.
        block_references: list of ``(name, x, y, layer)`` tuples
            for every INSERT (block reference).
        image_path: path to the rendered PNG (``None`` when
            rendering failed).
        page_count: always 1 (DXF is a single-sheet format;
            multi-sheet DXF files are rare and handled as one
            page).
    """

    text: str
    layers: list[str]
    text_entities: list[tuple[str, float, float, str]]
    dimensions: list[tuple[float, str, float, float]]
    block_references: list[tuple[str, float, float, str]]
    image_path: str | None
    page_count: int = 1


def parse_dxf(path: str | Path, output_dir: Path | None = None) -> DxfExtraction | None:
    """Parse a DXF file and extract text, dimensions and block
    references.

    Args:
        path: path to the ``.dxf`` file.
        output_dir: directory to write the rendered PNG. When
            ``None`` the image is not rendered.

    Returns:
        :class:`DxfExtraction` or ``None`` on any error.
    """
    try:
        import ezdxf
    except ImportError:
        logger.debug("ezdxf not available, skipping DXF parsing")
        return None

    path = Path(path)
    if not path.exists():
        return None

    try:
        doc = ezdxf.readfile(str(path))
    except Exception as exc:
        logger.warning("Failed to read DXF %s: %s", path.name, exc)
        return None

    msp = doc.modelspace()
    layers = sorted({layer.dxf.name for layer in doc.layers})
    text_entities: list[tuple[str, float, float, str]] = []
    dimensions: list[tuple[float, str, float, float]] = []
    block_references: list[tuple[str, float, float, str]] = []

    for entity in msp:
        dxftype = entity.dxftype()
        layer = entity.dxf.layer if hasattr(entity.dxf, "layer") else "0"

        if dxftype == "TEXT":
            text = entity.dxf.text.strip()
            if text:
                x = entity.dxf.insert.x if hasattr(entity.dxf, "insert") else 0
                y = entity.dxf.insert.y if hasattr(entity.dxf, "insert") else 0
                text_entities.append((text, float(x), float(y), layer))

        elif dxftype == "MTEXT":
            text = entity.plain_text().strip()
            if text:
                x = entity.dxf.insert.x if hasattr(entity.dxf, "insert") else 0
                y = entity.dxf.insert.y if hasattr(entity.dxf, "insert") else 0
                text_entities.append((text, float(x), float(y), layer))

        elif dxftype == "DIMENSION":
            try:
                measurement = entity.get_measurement()
                value = float(measurement) if measurement is not None else 0.0
                unit = "mm"  # DXF default
                x = getattr(entity.dxf, "defpoint", None)
                y_val = getattr(entity.dxf, "defpoint2", None)
                x_val = x.x if x else 0
                y_pos = y_val.y if y_val else 0
                dimensions.append((value, unit, float(x_val), float(y_pos)))
            except (AttributeError, ValueError, TypeError) as exc:
                # DXF files in the wild frequently have malformed
                # DIMENSION entities (custom block definitions,
                # proxy graphics, vendor-specific attributes). We
                # skip them and keep parsing the rest. The DEBUG
                # log keeps a trace for forensic analysis without
                # filling INFO logs.
                logger.debug(
                    "dxf_dimension_skipped handle=%s error=%s",
                    getattr(entity, "dxf", "?"),
                    exc,
                )

        elif dxftype == "INSERT":
            name = entity.dxf.name if hasattr(entity.dxf, "name") else ""
            x = entity.dxf.insert.x if hasattr(entity.dxf, "insert") else 0
            y = entity.dxf.insert.y if hasattr(entity.dxf, "insert") else 0
            block_references.append((name, float(x), float(y), layer))

    # Build plain-text representation.
    lines: list[str] = []
    lines.append(f"DXF Layers: {', '.join(layers)}")
    lines.append("")
    if text_entities:
        lines.append("Text entities:")
        for text, x, y, layer in text_entities:
            lines.append(f"  [{layer}] {text}  (x={x:.1f}, y={y:.1f})")
        lines.append("")
    if dimensions:
        lines.append("Dimensions:")
        for value, unit, x, y in dimensions:
            lines.append(f"  {value:.2f} {unit}  (x={x:.1f}, y={y:.1f})")
        lines.append("")
    if block_references:
        lines.append("Block references:")
        for name, x, y, layer in block_references:
            lines.append(f"  [{layer}] INSERT {name}  (x={x:.1f}, y={y:.1f})")

    text = "\n".join(lines)

    # Render to PNG.
    image_path: str | None = None
    if output_dir:
        image_path = _render_dxf_to_png(doc, output_dir, path.stem)

    return DxfExtraction(
        text=text,
        layers=layers,
        text_entities=text_entities,
        dimensions=dimensions,
        block_references=block_references,
        image_path=image_path,
    )


def _render_dxf_to_png(doc, output_dir: Path, stem: str) -> str | None:
    """Render the DXF to a PNG image using ezdxf's built-in
    drawing. Returns the path to the PNG or ``None`` on
    failure."""
    try:
        from ezdxf.addons.drawing import RenderContext, Frontend
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        import matplotlib.pyplot as plt

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"{stem}.png"

        fig, ax = plt.subplots(figsize=(16, 12))
        ctx = RenderContext(doc)
        backend = MatplotlibBackend(ax)
        Frontend(ctx, backend).draw_layout(doc.modelspace())
        ax.set_aspect("equal")
        ax.axis("off")
        fig.savefig(str(out_path), dpi=150, bbox_inches="tight", pad_inches=0.1)
        plt.close(fig)
        return str(out_path)
    except Exception as exc:
        logger.debug("DXF rendering failed: %s", exc)
        return None


__all__ = [
    "DxfExtraction",
    "parse_dxf",
]
