"""P1 — DZI (Deep Zoom Image) tile generation for the plan viewer.

The plan viewer needs to display large plan images (7000×10000
px) at multiple zoom levels without loading the entire image
into memory. DZI is a tiling format used by OpenSeadragon,
Leaflet, and other deep-zoom viewers: the image is pre-rendered
into a pyramid of tiles (256×256 px each) at progressively
higher resolutions.

This module generates DZI tiles on demand and caches them in
the filesystem so subsequent requests are instant. The tile
generation uses Pillow (already in requirements.txt) and
requires no additional dependencies.

The module is **fail-safe**: on any error (missing image,
corrupt file, out-of-memory) the function returns ``None`` so
the viewer shows a placeholder instead of crashing.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

logger = logging.getLogger("app.services.dzi_tiles")

TILE_SIZE = 256
OVERLAP = 1  # 1px overlap between adjacent tiles


def generate_dzi_tiles(
    image_path: str | Path,
    output_dir: str | Path,
    *,
    tile_size: int = TILE_SIZE,
) -> Path | None:
    """Generate a DZI tile pyramid from a plan image.

    Args:
        image_path: path to the source image (PNG/JPG).
        output_dir: directory to write the tiles. A subdirectory
            ``<stem>_files/`` is created inside ``output_dir``
            with the tile pyramid.
        tile_size: tile size in pixels (default 256).

    Returns:
        The path to the ``.dzi`` descriptor file, or ``None``
        on any error.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.debug("Pillow not available, skipping DZI generation")
        return None

    image_path = Path(image_path)
    output_dir = Path(output_dir)
    if not image_path.exists():
        return None

    try:
        img = Image.open(image_path)
        width, height = img.size
        if width <= 0 or height <= 0:
            return None

        # Compute the number of levels.
        max_dim = max(width, height)
        levels = max(1, math.ceil(math.log2(max_dim / tile_size)) + 1)

        # Create output directory.
        stem = image_path.stem
        tiles_dir = output_dir / f"{stem}_files"
        tiles_dir.mkdir(parents=True, exist_ok=True)

        # Generate tiles at each level.
        for level in range(levels):
            scale = 2 ** (levels - level - 1)
            level_w = math.ceil(width / scale)
            level_h = math.ceil(height / scale)
            level_img = img.resize((level_w, level_h), Image.Resampling.LANCZOS)
            level_dir = tiles_dir / str(level)
            level_dir.mkdir(parents=True, exist_ok=True)

            cols = math.ceil(level_w / tile_size)
            rows = math.ceil(level_h / tile_size)

            for col in range(cols):
                for row in range(rows):
                    x = col * tile_size
                    y = row * tile_size
                    tile_w = min(tile_size, level_w - x)
                    tile_h = min(tile_size, level_h - y)
                    tile = level_img.crop((x, y, x + tile_w, y + tile_h))
                    tile_path = level_dir / f"{col}_{row}.jpg"
                    tile.save(str(tile_path), "JPEG", quality=85)

        # Write the .dzi descriptor.
        dzi_path = output_dir / f"{stem}.dzi"
        dzi_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<Image xmlns="http://schemas.microsoft.com/deepzoom/2008"'
            f' Format="jpeg" Overlap="{OVERLAP}" TileSize="{tile_size}">\n'
            f'  <Size Width="{width}" Height="{height}"/>\n'
            f"</Image>\n"
        )
        dzi_path.write_text(dzi_content, encoding="utf-8")
        return dzi_path

    except Exception as exc:
        logger.warning("DZI generation failed for %s: %s", image_path.name, exc)
        return None


__all__ = [
    "generate_dzi_tiles",
    "TILE_SIZE",
]
