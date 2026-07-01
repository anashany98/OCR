from __future__ import annotations

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
    page = ExtractedPage(
        page_number=1,
        width=float(width),
        height=float(height),
        text=result.text,
        image_path=str(path),
        ocr_confidence=result.confidence,
        ocr_engine=actual_engine,
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
            import asyncio

            from app.ai.local_client import LocalVisionClient
            from app.services.vision_manager import VisionManager

            VisionManager.cancel_pending_unload()
            if not VisionManager.is_loaded():
                VisionManager.ensure_loaded()
            client = LocalVisionClient()
            loop = asyncio.new_event_loop()
            try:
                prompt = _get_vision_prompt(content_route)
                vision_text = loop.run_until_complete(
                    client.describe(path, prompt=prompt, max_tokens=2000)
                )
            finally:
                loop.close()
            if vision_text:
                page.blocks.append(
                    ExtractedBlock(
                        block_type="table",
                        text=vision_text,
                        page_number=1,
                        bbox=(0.0, 0.0, float(width), float(height)),
                        confidence=0.85,
                        source_engine="vision",
                    )
                )
                if not result.text or len(result.text.strip()) < 30:
                    page.text = vision_text
                    page.ocr_engine = "vision"
                    page.ocr_confidence = 0.85
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
