"""Content-aware document router.

Before running the full OCR pipeline, this module classifies the
document's visual content and selects the optimal processing path:

- PDFs with embedded text → standard OCR
- PDFs with scanned images → VLM-assisted OCR
- PDFs that are blueprints/plans → plan-specific pipeline
- Images of furniture/sketches → interior design VLM pipeline
- Images of fabric samples → description VLM pipeline
- Excel/Word → text extraction (no OCR needed)

The router is cheap (file extension + optional quick scan) and runs
before the expensive OCR/embedding steps. It does NOT replace the
existing classification (which runs AFTER OCR on the extracted text);
it PRE-CLASSIFIES the visual content to choose the right pipeline.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger("app.parsers.content_router")


class ContentRoute(Enum):
    """Processing routes for different content types."""

    STANDARD_OCR = "standard_ocr"  # Tesseract/PaddleOCR cascade
    VLM_OCR = "vlm_ocr"  # Vision LLM for scanned docs
    INTERIOR_DESIGN = "interior_design"  # Furniture/sketches/croquis
    FABRIC_DESCRIPTION = "fabric_description"  # Fabric samples
    TEXT_ONLY = "text_only"  # Excel/Word/plain text
    PLAN_OCR = "plan_ocr"  # Architectural plans with measurements


@dataclass(frozen=True)
class ContentClassification:
    route: ContentRoute
    confidence: float
    reason: str
    suggested_ocr_domain: str | None = None


# Keywords that suggest interior design / furniture content
_INTERIOR_KEYWORDS = {
    "cortina", "cortinas", "tela", "telas", "mueble", "muebles",
    "sillón", "sillon", "sofá", "sofa", "mesa", "silla", "sillas",
    "armario", "estantería", "estanteria", "cocina", "baño", "bano",
    "dormitorio", "salón", "salon", "comedor", "terraza",
    "persiana", "persianas", "visillo", "visillos", "tapizado",
    "forro", "toldo", "toldos", "banderola", "panel", "paneles",
    "medida", "medidas", "ancho", "largo", "alto", "caída", "cadam",
    "rosca", "bastidor", "barra", "guía", "guia",
}

# Keywords that suggest architectural plans
_PLAN_KEYWORDS = {
    "escala", "planta", "sección", "seccion", "alzado", "cota", "cotas",
    "m²", "m2", "mm", "área", "area", "perímetro", "perimetro",
    "pared", "puerta", "ventana", "columna", "viga",
}

# Scale patterns: "1:100", "Escala 1:50", "1/100"
_SCALE_RE = re.compile(r"(\d+\s*:\s*\d+|escala\s+\d+\s*:\s*\d+)", re.IGNORECASE)

# Dimension patterns: "3.50", "2,5 m", "150mm", "3500"
_DIMENSION_RE = re.compile(
    r"\b(\d+[.,]\d+\s*(?:m|cm|mm)?)\b|\b(\d{3,4}\s*(?:mm|cm))\b",
    re.IGNORECASE,
)

# File extensions that are always text-only (no OCR needed)
_TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".log", ".eml", ".msg"}
_EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}
_DOC_EXTENSIONS = {".doc", ".docx"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
_DXF_EXTENSIONS = {".dxf"}


def _quick_pdf_text_sample(path: Path, max_pages: int = 3) -> str:
    """Extract text from the first N pages of a PDF quickly.

    This is a cheap pre-scan: no OCR, no image rendering. Just
    grabs embedded text from the PDF structure. For scanned PDFs
    this returns empty (the text is in images, not in the PDF stream).
    """
    try:
        import fitz

        text_parts: list[str] = []
        with fitz.open(str(path)) as pdf:
            for i, page in enumerate(pdf):
                if i >= max_pages:
                    break
                text_parts.append(page.get_text("text"))
        return "\n".join(text_parts)
    except Exception as exc:
        logger.debug("quick_pdf_text_sample failed for %s: %s", path, exc)
        return ""


def _is_likely_plan(text: str) -> tuple[bool, float, str]:
    """Analyze extracted text to determine if it looks like a plan/blueprint.

    Returns (is_plan, confidence, reason).
    """
    text_lower = text.lower()

    # Check for scale patterns — strongest signal for plans
    scale_matches = _SCALE_RE.findall(text)
    if scale_matches:
        return True, 0.85, f"scale_pattern_found={scale_matches[0]}"

    # Count plan-specific keywords
    plan_hits = sum(1 for kw in _PLAN_KEYWORDS if kw in text_lower)
    if plan_hits >= 3:
        return True, min(0.8, 0.5 + plan_hits * 0.05), f"plan_keywords={plan_hits}"

    # Count dimension patterns (many measurements = likely a plan)
    dim_matches = _DIMENSION_RE.findall(text)
    dim_count = len([d for d in dim_matches if d[0] or d[1]])
    if dim_count >= 5:
        return True, min(0.75, 0.4 + dim_count * 0.03), f"many_dimensions={dim_count}"

    # Check for coordinate-like patterns (x,y coordinates in plans)
    coord_pattern = re.compile(r"\(\s*\d+[.,]?\d*\s*[;,]\s*\d+[.,]?\d*\s*\)")
    if len(coord_pattern.findall(text)) >= 3:
        return True, 0.65, "coordinate_patterns_found"

    # Low text + many images on page = likely scanned plan
    # (This is checked at the PDF page level, not here)

    return False, 0.0, "no_plan_signals"


def _is_likely_interior_design(text: str) -> tuple[bool, float, str]:
    """Analyze extracted text to determine if it's interior design content."""
    text_lower = text.lower()
    interior_hits = sum(1 for kw in _INTERIOR_KEYWORDS if kw in text_lower)
    if interior_hits >= 2:
        return True, min(0.8, 0.5 + interior_hits * 0.1), f"interior_keywords={interior_hits}"
    return False, 0.0, "no_interior_signals"


def classify_content(
    path: Path,
    extracted_text: str | None = None,
    folder_hint: str | None = None,
) -> ContentClassification:
    """Classify the content of a document and recommend a processing route.

    Args:
        path: file path (used for extension + filename heuristics)
        extracted_text: if already available (e.g. from a quick text
            extraction), used for keyword matching. Otherwise, the
            router uses filename/folder heuristics only.
        folder_hint: the subfolder name under input_dir (e.g.
            "presupuestos", "imagenes", "planos")
    """
    ext = path.suffix.lower()
    filename_lower = path.stem.lower()

    # --- Text-only files: no OCR needed ---
    if ext in _TEXT_EXTENSIONS or ext in _EXCEL_EXTENSIONS or ext in _DOC_EXTENSIONS:
        return ContentClassification(
            route=ContentRoute.TEXT_ONLY,
            confidence=1.0,
            reason=f"extension={ext}",
        )

    # --- DXF files: CAD drawings ---
    if ext in _DXF_EXTENSIONS:
        return ContentClassification(
            route=ContentRoute.STANDARD_OCR,
            confidence=1.0,
            reason=f"extension={ext}, using DXF parser",
        )

    # --- Folder-based hints ---
    if folder_hint:
        folder_lower = folder_hint.lower()
        if folder_lower in ("imagenes", "images", "fotos", "furniture", "muebles"):
            return ContentClassification(
                route=ContentRoute.INTERIOR_DESIGN,
                confidence=0.7,
                reason=f"folder_hint={folder_hint}",
                suggested_ocr_domain="interior_design",
            )
        if folder_lower in ("planos", "plans", "blueprints"):
            return ContentClassification(
                route=ContentRoute.PLAN_OCR,
                confidence=0.7,
                reason=f"folder_hint={folder_hint}",
            )
        if folder_lower in ("telas", "fabrics", "muestras"):
            return ContentClassification(
                route=ContentRoute.FABRIC_DESCRIPTION,
                confidence=0.7,
                reason=f"folder_hint={folder_hint}",
                suggested_ocr_domain="interior_design",
            )

    # --- Filename heuristics ---
    if any(kw in filename_lower for kw in ("croquis", "medida", "plano", "blueprint")):
        return ContentClassification(
            route=ContentRoute.INTERIOR_DESIGN,
            confidence=0.6,
            reason="filename_contains=croquis/medida/plano",
            suggested_ocr_domain="interior_design",
        )
    if any(kw in filename_lower for kw in ("tela", "fabric", "muestra", "sample")):
        return ContentClassification(
            route=ContentRoute.FABRIC_DESCRIPTION,
            confidence=0.6,
            reason="filename_contains=tela/fabric/muestra",
            suggested_ocr_domain="interior_design",
        )

    # --- PDF-specific: content analysis on first pages ---
    if ext == ".pdf":
        # Filename suggests plan
        if any(kw in filename_lower for kw in ("plano", "alzado", "seccion", "plantilla")):
            return ContentClassification(
                route=ContentRoute.PLAN_OCR,
                confidence=0.6,
                reason="pdf_filename_suggests_plan",
            )

        # Quick text sample from first pages to detect content type
        text_sample = extracted_text or _quick_pdf_text_sample(path)

        # Check if it's a plan based on content
        is_plan, plan_conf, plan_reason = _is_likely_plan(text_sample)
        if is_plan:
            return ContentClassification(
                route=ContentRoute.PLAN_OCR,
                confidence=plan_conf,
                reason=f"pdf_content_{plan_reason}",
            )

        # Check if it's interior design content
        is_interior, int_conf, int_reason = _is_likely_interior_design(text_sample)
        if is_interior:
            return ContentClassification(
                route=ContentRoute.INTERIOR_DESIGN,
                confidence=int_conf,
                reason=f"pdf_content_{int_reason}",
                suggested_ocr_domain="interior_design",
            )

        # Default PDF route: standard OCR
        return ContentClassification(
            route=ContentRoute.STANDARD_OCR,
            confidence=0.8,
            reason="pdf_default",
        )

    # --- Image routing based on extracted text keywords ---
    if ext in _IMAGE_EXTENSIONS:
        text_lower = (extracted_text or "").lower()

        # Check for interior design keywords
        interior_hits = sum(1 for kw in _INTERIOR_KEYWORDS if kw in text_lower)
        if interior_hits >= 2:
            return ContentClassification(
                route=ContentRoute.INTERIOR_DESIGN,
                confidence=min(0.9, 0.5 + interior_hits * 0.1),
                reason=f"image_text_interior_hits={interior_hits}",
                suggested_ocr_domain="interior_design",
            )

        # Check for plan keywords
        plan_hits = sum(1 for kw in _PLAN_KEYWORDS if kw in text_lower)
        if plan_hits >= 2:
            return ContentClassification(
                route=ContentRoute.PLAN_OCR,
                confidence=min(0.9, 0.5 + plan_hits * 0.1),
                reason=f"image_text_plan_hits={plan_hits}",
            )

        # Image with no text or very little text → likely a photo
        # (of furniture, fabric, etc.) → use VLM for description
        if not extracted_text or len(extracted_text.strip()) < 20:
            return ContentClassification(
                route=ContentRoute.INTERIOR_DESIGN,
                confidence=0.5,
                reason="image_no_text_likely_photo",
                suggested_ocr_domain="interior_design",
            )

    # --- Default: standard OCR cascade ---
    return ContentClassification(
        route=ContentRoute.STANDARD_OCR,
        confidence=0.5,
        reason="default_fallback",
    )


__all__ = [
    "ContentRoute",
    "ContentClassification",
    "classify_content",
    "_quick_pdf_text_sample",
    "_is_likely_plan",
]


def classify_content(
    path: Path,
    extracted_text: str | None = None,
    folder_hint: str | None = None,
) -> ContentClassification:
    """Classify the content of a document and recommend a processing route.

    Args:
        path: file path (used for extension + filename heuristics)
        extracted_text: if already available (e.g. from a quick text
            extraction), used for keyword matching. Otherwise, the
            router uses filename/folder heuristics only.
        folder_hint: the subfolder name under input_dir (e.g.
            "presupuestos", "imagenes", "planos")
    """
    ext = path.suffix.lower()
    filename_lower = path.stem.lower()

    # --- Text-only files: no OCR needed ---
    if ext in _TEXT_EXTENSIONS or ext in _EXCEL_EXTENSIONS or ext in _DOC_EXTENSIONS:
        return ContentClassification(
            route=ContentRoute.TEXT_ONLY,
            confidence=1.0,
            reason=f"extension={ext}",
        )

    # --- DXF files: CAD drawings ---
    if ext in _DXF_EXTENSIONS:
        return ContentClassification(
            route=ContentRoute.STANDARD_OCR,
            confidence=1.0,
            reason=f"extension={ext}, using DXF parser",
        )

    # --- Folder-based hints ---
    if folder_hint:
        folder_lower = folder_hint.lower()
        if folder_lower in ("imagenes", "images", "fotos", "furniture", "muebles"):
            return ContentClassification(
                route=ContentRoute.INTERIOR_DESIGN,
                confidence=0.7,
                reason=f"folder_hint={folder_hint}",
                suggested_ocr_domain="interior_design",
            )
        if folder_lower in ("planos", "plans", "blueprints"):
            return ContentClassification(
                route=ContentRoute.PLAN_OCR,
                confidence=0.7,
                reason=f"folder_hint={folder_hint}",
            )
        if folder_lower in ("telas", "fabrics", "muestras"):
            return ContentClassification(
                route=ContentRoute.FABRIC_DESCRIPTION,
                confidence=0.7,
                reason=f"folder_hint={folder_hint}",
                suggested_ocr_domain="interior_design",
            )

    # --- Filename heuristics ---
    if any(kw in filename_lower for kw in ("croquis", "medida", "plano", "blueprint")):
        return ContentClassification(
            route=ContentRoute.INTERIOR_DESIGN,
            confidence=0.6,
            reason="filename_contains=croquis/medida/plano",
            suggested_ocr_domain="interior_design",
        )
    if any(kw in filename_lower for kw in ("tela", "fabric", "muestra", "sample")):
        return ContentClassification(
            route=ContentRoute.FABRIC_DESCRIPTION,
            confidence=0.6,
            reason="filename_contains=tela/fabric/muestra",
            suggested_ocr_domain="interior_design",
        )

    # --- PDF-specific routing ---
    if ext == ".pdf":
        # Check if the filename suggests a plan/drawing
        if any(kw in filename_lower for kw in ("plano", "alzado", "seccion", "plantilla")):
            return ContentClassification(
                route=ContentRoute.PLAN_OCR,
                confidence=0.6,
                reason="pdf_filename_suggests_plan",
            )
        # Default PDF route: standard OCR (will escalate to VLM if needed)
        return ContentClassification(
            route=ContentRoute.STANDARD_OCR,
            confidence=0.8,
            reason="pdf_default",
        )

    # --- Image routing based on extracted text keywords ---
    if ext in _IMAGE_EXTENSIONS:
        text_lower = (extracted_text or "").lower()

        # Check for interior design keywords
        interior_hits = sum(1 for kw in _INTERIOR_KEYWORDS if kw in text_lower)
        if interior_hits >= 2:
            return ContentClassification(
                route=ContentRoute.INTERIOR_DESIGN,
                confidence=min(0.9, 0.5 + interior_hits * 0.1),
                reason=f"image_text_interior_hits={interior_hits}",
                suggested_ocr_domain="interior_design",
            )

        # Check for plan keywords
        plan_hits = sum(1 for kw in _PLAN_KEYWORDS if kw in text_lower)
        if plan_hits >= 2:
            return ContentClassification(
                route=ContentRoute.PLAN_OCR,
                confidence=min(0.9, 0.5 + plan_hits * 0.1),
                reason=f"image_text_plan_hits={plan_hits}",
            )

        # Image with no text or very little text → likely a photo
        # (of furniture, fabric, etc.) → use VLM for description
        if not extracted_text or len(extracted_text.strip()) < 20:
            return ContentClassification(
                route=ContentRoute.INTERIOR_DESIGN,
                confidence=0.5,
                reason="image_no_text_likely_photo",
                suggested_ocr_domain="interior_design",
            )

    # --- Default: standard OCR cascade ---
    return ContentClassification(
        route=ContentRoute.STANDARD_OCR,
        confidence=0.5,
        reason="default_fallback",
    )


__all__ = ["ContentRoute", "ContentClassification", "classify_content"]
