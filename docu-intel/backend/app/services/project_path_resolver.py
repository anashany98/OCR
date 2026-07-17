"""Phase 3 — Path resolver for the fixed corpus hierarchy.

Resolves a file path like:
  2025/Marca/Hotel/Presupuesto XXXXX/category/file.pdf
into structured metadata (brand, hotel, budget code, category).

Algorithm (from PLAN_MIMO_2_5 §3):
  1. Normalize separators without changing persisted original.
  2. Find a segment matching ^Presupuesto\\s+(.+)$.
  3. Reject generic names as budget codes: PDF, CORREOS, EXCEL, etc.
  4. Segment after Presupuesto is the document category.
  5. First segment after year is brand/group.
  6. Segment between brand and Presupuesto (if any) is hotel.
  7. If Presupuesto is directly under brand, hotel_id = null.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Generic folder names that must NOT be treated as budget codes
_REJECTED_BUDGET_NAMES = frozenset(
    {
        "pdf",
        "correos",
        "excel",
        "imagenes",
        "planos",
        "word",
        "otros",
        "zip",
        "img",
        "images",
        "docs",
        "documents",
    }
)

_BUDGET_PATTERN = re.compile(r"^Presupuesto\s+(.+)$", re.IGNORECASE)
_YEAR_PATTERN = re.compile(r"^\d{4}$")


@dataclass(frozen=True)
class PathResolution:
    """Result of resolving a corpus file path."""

    year: int | None
    brand: str | None
    hotel: str | None
    budget_code: str | None
    category: str | None
    original_segments: list[str]


def normalize_separators(path: str) -> str:
    """Normalize backslashes to forward slashes without altering the value."""
    return path.replace("\\", "/")


def resolve_corpus_path(path: str, source_root: str = "") -> PathResolution:
    """Resolve a corpus file path into structured components.

    Args:
        path: The full source path (e.g. "D:/TEST2025/2025/Marca/Hotel/Presupuesto 12345/PDF/file.pdf")
        source_root: The root mount point (e.g. "D:/TEST2025/2025" or "/app/source/2025")
    """
    normalized = normalize_separators(path)

    # Extract year from the full path (may be in source_root or in segments)
    year: int | None = None
    for seg in normalized.split("/"):
        if _YEAR_PATTERN.match(seg):
            try:
                year = int(seg)
                break
            except ValueError:
                continue

    # Strip the source root prefix if present
    if source_root:
        root_norm = normalize_separators(source_root).rstrip("/")
        if normalized.startswith(root_norm):
            normalized = normalized[len(root_norm) :]
    # Remove leading slash
    normalized = normalized.lstrip("/")

    segments = [s for s in normalized.split("/") if s]

    brand: str | None = None
    hotel: str | None = None
    budget_code: str | None = None
    category: str | None = None

    # Find year segment index (for remaining calculation)
    year_idx = None
    for i, seg in enumerate(segments):
        if _YEAR_PATTERN.match(seg):
            try:
                year_idx = i
                break
            except ValueError:
                continue

    # No year means the hierarchy starts directly with the brand.
    remaining = segments if year_idx is None else segments[year_idx + 1 :]

    # Uploaded folder trees are namespaced as ``upload/<user-id>/...``.
    # They are not part of the immutable corpus, but the hierarchy is still
    # explicit user-provided context after path sanitisation.  Remove only the
    # transport namespace so ``upload/7/Marca/Hotel/Presupuesto 123`` resolves
    # exactly like the corresponding corpus path.  A non-numeric second part
    # is a brand, not a user id, and is therefore kept.
    if remaining and remaining[0].lower() == "upload":
        remaining = remaining[1:]
        if remaining and remaining[0].isdigit():
            remaining = remaining[1:]

    if not remaining:
        return PathResolution(
            year=year,
            brand=None,
            hotel=None,
            budget_code=None,
            category=None,
            original_segments=segments,
        )

    # Find Presupuesto segment
    budget_idx = None
    for i, seg in enumerate(remaining):
        m = _BUDGET_PATTERN.match(seg)
        if m:
            code = m.group(1).strip()
            if code.lower() not in _REJECTED_BUDGET_NAMES:
                budget_idx = i
                budget_code = code
                break

    if budget_idx is not None:
        # Brand is the first segment after year (if any segments before Presupuesto)
        if budget_idx > 0:
            brand = remaining[0]
        # Hotel is between brand and Presupuesto (if more than one segment before)
        if budget_idx > 1:
            hotel = remaining[1]
        # Category is the segment after Presupuesto
        if budget_idx + 1 < len(remaining):
            category = remaining[budget_idx + 1]
    else:
        # No Presupuesto found; first segment is brand
        if remaining:
            brand = remaining[0]
        if len(remaining) > 1:
            # Could be hotel or category — treat second as hotel
            hotel = remaining[1]

    return PathResolution(
        year=year,
        brand=brand,
        hotel=hotel,
        budget_code=budget_code,
        category=category,
        original_segments=segments,
    )


def classify_category(filename: str, folder_category: str | None = None) -> str:
    """Map a filename or folder category to a normalized document category.

    Categories from the plan:
      presupuestos, pedidos, facturas, albaranes, planos, imagenes,
      croquis, incidencias, pagos, correos, otros
    """
    if folder_category:
        cat = folder_category.lower().strip()
        if cat in ("pdf", "presupuestos", "presupuesto"):
            return "presupuestos"
        if cat in ("excel", "pedidos"):
            return "pedidos"
        if cat in ("word",):
            return "otros"
        if cat in ("imagenes", "img", "images", "fotos"):
            return "imagenes"
        if cat in ("planos",):
            return "planos"
        if cat in ("correos", "correo"):
            return "correos"
        return cat

    name_lower = filename.lower()
    if name_lower.endswith((".xlsx", ".xls", ".xlsm")):
        return "pedidos"
    if "factura" in name_lower:
        return "facturas"
    if "albaran" in name_lower or "albarán" in name_lower:
        return "albaranes"
    if "pedido" in name_lower:
        return "pedidos"
    if "presupuesto" in name_lower:
        return "presupuestos"
    if "croquis" in name_lower or "medicion" in name_lower:
        return "croquis"
    if "plano" in name_lower:
        return "planos"
    if "incidencia" in name_lower:
        return "incidencias"
    if "pago" in name_lower:
        return "pagos"
    if name_lower.endswith((".msg", ".eml")):
        return "correos"
    if name_lower.endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp")):
        return "imagenes"
    return "otros"
