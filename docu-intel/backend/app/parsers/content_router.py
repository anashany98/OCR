"""Content-aware document router.

Cheap pre-routing for visual documents. It selects a processing hint before
the expensive OCR pass, but final document classification still happens after
text extraction.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger("app.parsers.content_router")


class ContentRoute(Enum):
    STANDARD_OCR = "standard_ocr"
    VLM_OCR = "vlm_ocr"
    INTERIOR_DESIGN = "interior_design"
    FABRIC_DESCRIPTION = "fabric_description"
    TEXT_ONLY = "text_only"
    PLAN_OCR = "plan_ocr"


@dataclass(frozen=True)
class ContentClassification:
    route: ContentRoute
    confidence: float
    reason: str
    suggested_ocr_domain: str | None = None


_INTERIOR_KEYWORDS = {
    "cortina",
    "cortinas",
    "tela",
    "telas",
    "mueble",
    "muebles",
    "sillon",
    "sofa",
    "mesa",
    "silla",
    "sillas",
    "armario",
    "estanteria",
    "cocina",
    "bano",
    "dormitorio",
    "salon",
    "comedor",
    "terraza",
    "persiana",
    "persianas",
    "visillo",
    "visillos",
    "tapizado",
    "forro",
    "toldo",
    "toldos",
    "banderola",
    "panel",
    "paneles",
    "medida",
    "medidas",
    "ancho",
    "largo",
    "alto",
    "caida",
    "cadam",
    "rosca",
    "bastidor",
    "barra",
    "guia",
}

_PLAN_KEYWORDS = {
    "escala",
    "planta",
    "seccion",
    "alzado",
    "cota",
    "cotas",
    "m2",
    "area",
    "perimetro",
    "pared",
    "puerta",
    "ventana",
    "columna",
    "viga",
}

_PLAN_FILENAME_KEYWORDS = ("plano", "alzado", "seccion")
_INTERIOR_FILENAME_KEYWORDS = ("croquis", "medida")
_FABRIC_FILENAME_KEYWORDS = ("tela", "fabric", "muestra", "sample")
_PLAN_FOLDERS = {"planos", "plans", "blueprints"}
_INTERIOR_FOLDERS = {"imagenes", "images", "fotos", "furniture", "muebles"}
_FABRIC_FOLDERS = {"telas", "fabrics", "muestras"}

_SCALE_RE = re.compile(r"\b(?:escala\s*)?1\s*[:/]\s*\d{1,5}\b", re.IGNORECASE)
_DIMENSION_RE = re.compile(
    r"\b\d+[.,]\d+\s*(?:m|cm|mm)?\b|\b\d{3,4}\s*(?:mm|cm)\b",
    re.IGNORECASE,
)
_COORD_RE = re.compile(r"\(\s*\d+[.,]?\d*\s*[;,]\s*\d+[.,]?\d*\s*\)")

_TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".log", ".eml", ".msg"}
_EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}
_DOC_EXTENSIONS = {".doc", ".docx"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
_DXF_EXTENSIONS = {".dxf"}


def _normalise(value: str) -> str:
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ü": "u",
        "ñ": "n",
    }
    lowered = value.lower()
    for src, dst in replacements.items():
        lowered = lowered.replace(src, dst)
    return " ".join(lowered.split())


def _quick_pdf_text_sample(path: Path, max_pages: int = 3) -> str:
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
    normalized = _normalise(text)
    if _SCALE_RE.search(normalized):
        return True, 0.9, "scale_pattern_found"

    plan_hits = sum(1 for kw in _PLAN_KEYWORDS if re.search(rf"\b{re.escape(kw)}\b", normalized))
    dimension_count = len(_DIMENSION_RE.findall(normalized))
    coord_count = len(_COORD_RE.findall(normalized))

    if plan_hits >= 3:
        return True, min(0.82, 0.5 + plan_hits * 0.06), f"plan_keywords={plan_hits}"
    if plan_hits >= 2 and dimension_count >= 3:
        return True, min(0.78, 0.5 + dimension_count * 0.04), f"plan_keywords={plan_hits},dimensions={dimension_count}"
    if dimension_count >= 6:
        return True, min(0.72, 0.38 + dimension_count * 0.035), f"many_dimensions={dimension_count}"
    if coord_count >= 3:
        return True, 0.65, "coordinate_patterns_found"
    return False, 0.0, "no_plan_signals"


def _is_likely_interior_design(text: str) -> tuple[bool, float, str]:
    normalized = _normalise(text)
    interior_hits = sum(
        1 for kw in _INTERIOR_KEYWORDS if re.search(rf"\b{re.escape(kw)}\b", normalized)
    )
    if interior_hits >= 2:
        return True, min(0.85, 0.5 + interior_hits * 0.08), f"interior_keywords={interior_hits}"
    return False, 0.0, "no_interior_signals"


def _plan_filename_match(filename: str) -> bool:
    return any(re.search(rf"\b{keyword}\b", filename) for keyword in _PLAN_FILENAME_KEYWORDS)


def _image_is_too_small(path: Path, *, min_side: int = 64) -> bool:
    """Return True if the image's shorter side is below ``min_side``.

    Used to avoid the "no text sample → must be a photo" assumption on
    degenerate inputs (thumbnails, 1×1 pixels) where the empty sample is
    just a consequence of the tiny size, not evidence of a photo. Reads
    only the header via PIL so it's cheap; any error returns False
    (fail to the existing photo assumption, preserving prior behaviour).
    """
    try:
        from PIL import Image

        with Image.open(path) as img:
            return min(img.size) < min_side
    except Exception:
        return False


def classify_content(
    path: Path,
    extracted_text: str | None = None,
    folder_hint: str | None = None,
) -> ContentClassification:
    ext = path.suffix.lower()
    filename = _normalise(path.stem)
    folder = _normalise(folder_hint or "")
    text_sample = extracted_text or ""

    if ext in _TEXT_EXTENSIONS or ext in _EXCEL_EXTENSIONS or ext in _DOC_EXTENSIONS:
        return ContentClassification(ContentRoute.TEXT_ONLY, 1.0, f"extension={ext}")

    if ext in _DXF_EXTENSIONS:
        return ContentClassification(ContentRoute.STANDARD_OCR, 1.0, f"extension={ext}, using DXF parser")

    if folder in _INTERIOR_FOLDERS:
        return ContentClassification(
            ContentRoute.INTERIOR_DESIGN,
            0.7,
            f"folder_hint={folder_hint}",
            suggested_ocr_domain="interior_design",
        )

    if folder in _FABRIC_FOLDERS:
        return ContentClassification(
            ContentRoute.FABRIC_DESCRIPTION,
            0.7,
            f"folder_hint={folder_hint}",
            suggested_ocr_domain="interior_design",
        )

    if any(keyword in filename for keyword in _FABRIC_FILENAME_KEYWORDS):
        return ContentClassification(
            ContentRoute.FABRIC_DESCRIPTION,
            0.6,
            "filename_contains=fabric/tela/muestra",
            suggested_ocr_domain="interior_design",
        )

    if ext == ".pdf":
        text_sample = text_sample or _quick_pdf_text_sample(path)
        is_interior, interior_conf, interior_reason = _is_likely_interior_design(text_sample)
        if is_interior and not _plan_filename_match(filename):
            return ContentClassification(
                ContentRoute.INTERIOR_DESIGN,
                interior_conf,
                f"pdf_content_{interior_reason}",
                suggested_ocr_domain="interior_design",
            )

        is_plan, plan_conf, plan_reason = _is_likely_plan(text_sample)
        if is_plan or _plan_filename_match(filename):
            return ContentClassification(
                ContentRoute.PLAN_OCR,
                max(plan_conf, 0.65),
                f"pdf_content_{plan_reason}" if is_plan else "pdf_filename_suggests_plan",
            )

        return ContentClassification(ContentRoute.STANDARD_OCR, 0.8, "pdf_default")

    if ext in _IMAGE_EXTENSIONS:
        if any(keyword in filename for keyword in _INTERIOR_FILENAME_KEYWORDS):
            return ContentClassification(
                ContentRoute.INTERIOR_DESIGN,
                0.6,
                "filename_contains=croquis/medida",
                suggested_ocr_domain="interior_design",
            )

        is_interior, interior_conf, interior_reason = _is_likely_interior_design(text_sample)
        if is_interior:
            return ContentClassification(
                ContentRoute.INTERIOR_DESIGN,
                interior_conf,
                f"image_text_{interior_reason}",
                suggested_ocr_domain="interior_design",
            )

        is_plan, plan_conf, plan_reason = _is_likely_plan(text_sample)
        if is_plan or (folder in _PLAN_FOLDERS and _plan_filename_match(filename)):
            return ContentClassification(
                ContentRoute.PLAN_OCR,
                max(plan_conf, 0.65),
                f"image_text_{plan_reason}" if is_plan else "folder_and_filename_plan",
            )

        # CLIP fallback: use visual classification before text-based heuristics.
        # Confidence bar is high (0.75): classifying an image as a product
        # photo routes it away from OCR entirely, so we only trust a strong
        # visual signal. A weak verdict falls through to the text-based
        # heuristics below.
        if ext in {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}:
            try:
                from app.parsers.clip_classifier import classify_image
                clip_result = classify_image(path)
                if clip_result["confidence"] > 0.75:
                    category = clip_result["category"]
                    if category == "document":
                        return ContentClassification(
                            ContentRoute.STANDARD_OCR,
                            clip_result["confidence"],
                            f"clip_{category}",
                        )
                    elif category == "product_photo":
                        return ContentClassification(
                            ContentRoute.INTERIOR_DESIGN,
                            clip_result["confidence"],
                            f"clip_{category}",
                            suggested_ocr_domain="interior_design",
                        )
                    elif category == "plan":
                        return ContentClassification(
                            ContentRoute.PLAN_OCR,
                            clip_result["confidence"],
                            f"clip_{category}",
                        )
            except Exception as exc:
                logger.debug("CLIP classification failed: %s", exc)

        if not text_sample or len(text_sample.strip()) < 20:
            # An image with no quick text sample is *assumed* to be a photo
            # — but only if it is large enough for that assumption to be
            # meaningful. Tiny / degenerate images (thumbnails, 1×1 pixels)
            # produce an empty sample simply because there's nothing to
            # sniff, not because they're photos; route them to OCR instead
            # so a valid small document isn't silently skipped.
            if _image_is_too_small(path):
                return ContentClassification(ContentRoute.STANDARD_OCR, 0.5, "tiny_image_default_ocr")
            return ContentClassification(
                ContentRoute.INTERIOR_DESIGN,
                0.5,
                "image_no_text_likely_photo",
                suggested_ocr_domain="interior_design",
            )

    if folder in _PLAN_FOLDERS and _plan_filename_match(filename):
        return ContentClassification(ContentRoute.PLAN_OCR, 0.65, "folder_and_filename_plan")

    return ContentClassification(ContentRoute.STANDARD_OCR, 0.5, "default_fallback")


__all__ = [
    "ContentRoute",
    "ContentClassification",
    "classify_content",
    "_quick_pdf_text_sample",
    "_is_likely_plan",
]
