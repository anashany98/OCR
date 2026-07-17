from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from app.core.config import settings
from app.ocr.base import BaseOCREngine
from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage

logger = logging.getLogger("app.parsers.image")


# Domain-specific prompts for the vision model fallback.
_PROMPT_GENERIC = (
    "Transcribe TODO el texto visible en esta imagen. "
    "Si hay texto manuscrito, transcribelo tal cual. "
    "Si hay una tabla, reproduce su contenido como tabla markdown. "
    "Si es una foto sin texto legible, describe brevemente "
    "que muestra la imagen. Responde en espanol."
)

_PROMPT_INTERIOR_DESIGN = (
    "Esta imagen es parte de un presupuesto de mobiliario, cortinas o interiorismo. "
    "Contiene probablemente: croquis a mano, fotos de muebles, muestras de telas, "
    "o medidas tomadas en campo sobre objetos reales.\n\n"
    "Analiza la imagen y responde con este formato EXACTO:\n\n"
    "## OBJETOS DETECTADOS\n"
    "Para cada objeto visible (mueble, cortina, tela, ventana, puerta, habitacion, etc.):\n"
    "- Nombre del objeto: descripcion breve\n"
    "- Medidas asociadas: ancho x largo x alto (las que aparezcan escritas o dibujadas)\n"
    "- Material/textura: si se distingue (tela, madera, metal, etc.)\n"
    "- Notas: cualquier anotacion manuscrita relacionada\n\n"
    "## COTAS Y MEDIDAS\n"
    "Lista TODAS las medidas numericas que aparezcan en la imagen, indicando:\n"
    "- Valor numerico y unidad (cm, m, mm)\n"
    "- A que objeto o espacio pertenece\n"
    "- Si la medida esta escrita a mano o es una cota tecnica\n\n"
    "## TEXTO MANUSCRITO\n"
    "Transcribe literalmente cualquier texto escrito a mano, sin interpretar.\n\n"
    "## DESCRIPCION VISUAL\n"
    "Describe brevemente que se ve en la imagen.\n\n"
    "Si no puedes leer una medida con certeza, indica 'ilegible' en vez de inventar un numero."
)

_PROMPT_FABRIC = (
    "Esta imagen es una muestra de tela o textil de un presupuesto de interiorismo.\n\n"
    "Describe:\n"
    "- Tipo de tela (cortina, tapizado, visillo, etc.)\n"
    "- Color y patron (liso, estampado, rayas, etc.)\n"
    "- Textura visible\n"
    "- Si hay medidas anotadas, listalas\n"
    "- Si hay codigo de muestra o referencia, transcribelo\n"
    "Responde en espanol."
)

# Phase 5: Sensitive data detection instructions appended to all prompts
_SENSITIVE_DATA_INSTRUCTIONS = (
    "\n\nIMPORTANTE: Si la imagen contiene datos sensibles, enumeralos:\n"
    "- Numeros de cuenta o IBAN\n"
    "- NIF, CIF o DNI\n"
    "- Telefonos o emails\n"
    "- Importes bancarios o datos de pago\n"
    "- Nombres de personas\n"
    "Si no hay datos sensibles, indica 'NINGUNO'."
)


def _estimate_vision_confidence(vision_text: str, content_route: str | None) -> float:
    """Estimate per-fact confidence from VLM response characteristics.

    Instead of hardcoding 0.85, we estimate based on:
    - Response length (longer = more detailed = higher confidence)
    - Content route match (interior_design/fabric with specific prompts = higher)
    - Presence of uncertainty markers ('ilegible', 'no se puede', 'posible')
    """
    if not vision_text:
        return 0.3

    base = 0.5
    text_len = len(vision_text.strip())

    # Length bonus
    if text_len > 500:
        base += 0.15
    elif text_len > 200:
        base += 0.1
    elif text_len > 50:
        base += 0.05

    # Content route bonus
    if content_route in ("interior_design", "fabric_description"):
        base += 0.1

    # Penalty for uncertainty markers
    uncertainty_markers = ["ilegible", "no se puede", "posible", "uncertain", "dudoso"]
    uncertainty_count = sum(1 for m in uncertainty_markers if m.lower() in vision_text.lower())
    base -= uncertainty_count * 0.05

    return max(0.3, min(base, 0.95))


def _get_vision_prompt(content_route: str | None = None) -> str:
    """Return the appropriate vision prompt based on content classification."""
    if content_route == "interior_design":
        return _PROMPT_INTERIOR_DESIGN
    if content_route == "fabric_description":
        return _PROMPT_FABRIC
    return _PROMPT_GENERIC


def parse_image(
    path: Path,
    output_dir: Path,
    ocr_engine: BaseOCREngine,
    content_route: str | None = None,
) -> ExtractedDocument:
    from PIL import Image

    with Image.open(path) as image:
        width, height = image.size
    megapixels = (width * height) / 1_000_000
    if megapixels > settings.max_image_megapixels:
        raise ValueError(
            f"max_image_megapixels exceeded: {megapixels:.2f} > {settings.max_image_megapixels}"
        )

    # Skip OCR for photos/interior design images — no text expected
    import logging

    _log = logging.getLogger("app.parsers.image")
    _log.info("parse_image content_route=%s path=%s", content_route, path.name)
    if content_route in ("interior_design", "fabric_description"):
        _log.info("OCR SKIPPED: photo/interior_design detected for %s", path.name)
        from app.ocr.base import OCRResult

        result = OCRResult(text="", confidence=0.0, blocks=[], engine="photo_skip")
    else:
        # FASE 5: set content_route on cascade for tier skipping.
        with contextlib.suppress(Exception):
            ocr_engine.current_content_route = content_route
            ocr_engine.current_page_number = 1
        result = ocr_engine.extract(path)
    actual_engine = result.engine or ocr_engine.name
    blocks = [
        ExtractedBlock(
            block_type="text",
            text=block.text,
            page_number=1,
            bbox=block.bbox,
            confidence=block.confidence,
            source_engine=actual_engine,
        )
        for block in result.blocks
    ]
    is_non_ocr_photo = actual_engine == "photo_skip"
    page = ExtractedPage(
        page_number=1,
        width=float(width),
        height=float(height),
        text=result.text,
        image_path=str(path),
        ocr_confidence=None if is_non_ocr_photo else result.confidence,
        ocr_content_kind="photo" if is_non_ocr_photo else (result.content_kind or "ocr"),
        ocr_engine=actual_engine,
        ocr_engine_version=result.engine_version,
        ocr_warnings=list(result.warnings),
        blocks=blocks,
    )

    # Vision fallback: if OCR couldn't extract enough text, use the
    # vision model with a content-aware prompt.
    needs_vision = (
        settings.vision_table_transcription
        and settings.vision_model
        and (not result.text or len(result.text.strip()) < 30 or (result.confidence or 0) < 0.5)
    )

    if needs_vision:
        try:
            from app.ai.local_client import LocalVisionClient
            from app.parsers.pdf import _run_coro_sync
            from app.services.vision_manager import VisionManager

            VisionManager.cancel_pending_unload()
            if not VisionManager.is_loaded():
                VisionManager.ensure_loaded()
            client = LocalVisionClient()
            prompt = _get_vision_prompt(content_route) + _SENSITIVE_DATA_INSTRUCTIONS
            vision_text = _run_coro_sync(client.describe(path, prompt=prompt, max_tokens=2000))
            if vision_text:
                # Phase 5: per-fact confidence instead of hardcoded 0.85
                vision_confidence = _estimate_vision_confidence(vision_text, content_route)
                # Phase 5: use "vision_description" block_type for image descriptions
                block_type = "vision_description" if len(vision_text) > 100 else "text"
                page.blocks.append(
                    ExtractedBlock(
                        block_type=block_type,
                        text=vision_text,
                        page_number=1,
                        bbox=(0.0, 0.0, float(width), float(height)),
                        confidence=vision_confidence,
                        source_engine="vision",
                    )
                )
                if not result.text or len(result.text.strip()) < 30:
                    page.text = vision_text
                    page.ocr_engine = "vision"
                    page.ocr_confidence = vision_confidence
            VisionManager.schedule_unload()
        except Exception as exc:
            from app.services.metrics import track_parser_fallback_failure

            logger.warning(
                "vision transcription fallback failed for %s: %s: %s",
                path,
                type(exc).__name__,
                exc,
            )
            track_parser_fallback_failure(stage="image_vision_transcribe", kind="exception")

    return ExtractedDocument(pages=[page])
