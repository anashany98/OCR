"""Phase 5 — Image classification taxonomy.

Multi-label taxonomy for classifying images in the corpus.
Each image can have multiple labels (e.g. a photo of a fabric sample
next to a measurement sketch could be both "muestra_material" and
"croquis_medicion").
"""

from __future__ import annotations

from enum import StrEnum


class ImageLabel(StrEnum):
    """Possible labels for an image in the corpus taxonomy."""

    FOTO_PRODUCTO = "foto_producto"
    FOTO_INSTALACION = "foto_instalacion"
    MUESTRA_MATERIAL = "muestra_material"
    CROQUIS_MEDICION = "croquis_medicion"
    PLANO_TECNICO = "plano_tecnico"
    DOCUMENTO_FOTOGRAFIADO = "documento_fotografiado"
    COMPROBANTE_PAGO = "comprobante_pago"
    INCIDENCIA = "incidencia"
    RENDER = "render"
    CAPTURA_PANTALLA = "captura_pantalla"
    LOGO_GRAFICO = "logo_grafico"
    DESCONOCIDO = "desconocido"


# Keywords that hint at each label (used in filename/folder heuristics)
LABEL_KEYWORDS: dict[ImageLabel, list[str]] = {
    ImageLabel.FOTO_PRODUCTO: [
        "producto",
        "mueble",
        "silla",
        "sofa",
        "mesa",
        "lampara",
        "cama",
        "armario",
        "estanteria",
        "muebles",
        "catalogo",
        "collection",
    ],
    ImageLabel.FOTO_INSTALACION: [
        "instalacion",
        "instalado",
        "resultado",
        "final",
        "terminado",
        "colocado",
        "ambiente",
        "room",
        "hotel",
    ],
    ImageLabel.MUESTRA_MATERIAL: [
        "tejido",
        "tela",
        "muestra",
        "fabric",
        "material",
        "color",
        "textura",
        "tapiceria",
        "upholstery",
        "lino",
        "algodon",
    ],
    ImageLabel.CROQUIS_MEDICION: [
        "croquis",
        "medicion",
        "medida",
        "dimension",
        "cota",
        "plano_mano",
        "boceto",
        "sketch",
        "dibujo_tecnico",
    ],
    ImageLabel.PLANO_TECNICO: [
        "plano",
        "blueprint",
        "layout",
        "distribucion",
        " planta",
        "electricidad",
        "fontaneria",
        "structural",
    ],
    ImageLabel.DOCUMENTO_FOTOGRAFIADO: [
        "documento",
        "escaneado",
        "scan",
        "fotografiado",
        "photo_doc",
    ],
    ImageLabel.COMPROBANTE_PAGO: [
        "pago",
        "recibo",
        "justificante",
        "transferencia",
        "factura_foto",
        "ticket",
        "receipt",
    ],
    ImageLabel.INCIDENCIA: [
        "incidencia",
        "dano",
        "problema",
        "averia",
        "rotura",
        "fallo",
        "reclamacion",
    ],
    ImageLabel.RENDER: [
        "render",
        "3d",
        "visualizacion",
        "visualization",
        "cgi",
    ],
    ImageLabel.CAPTURA_PANTALLA: [
        "screenshot",
        "captura",
        "screen",
    ],
    ImageLabel.LOGO_GRAFICO: [
        "logo",
        "icono",
        "brand",
        "marca_grafica",
    ],
}

# Folder name → primary label mapping
FOLDER_LABEL_MAP: dict[str, ImageLabel] = {
    "imagenes": ImageLabel.FOTO_PRODUCTO,  # default, overridden by filename
    "imagenes/instalacion": ImageLabel.FOTO_INSTALACION,
    "imagenes/pago": ImageLabel.COMPROBANTE_PAGO,
    "imagenes/incidencia": ImageLabel.INCIDENCIA,
    "imagenes/plano": ImageLabel.PLANO_TECNICO,
    "imagenes/render": ImageLabel.RENDER,
    "imagenes/croquis": ImageLabel.CROQUIS_MEDICION,
    "imagenes/tejido": ImageLabel.MUESTRA_MATERIAL,
    "planos": ImageLabel.PLANO_TECNICO,
    "croquis": ImageLabel.CROQUIS_MEDICION,
}


# Processing strategy per label
class ProcessingStrategy(StrEnum):
    """How to process an image based on its primary label."""

    OCR_FIRST = "ocr_first"  # Document, payment, screenshot
    VISION_ONLY = "vision_only"  # Product, installation, material
    OCR_PLUS_VISION = "ocr_plus_vision"  # Sketch, plan, photo document
    VISION_PLUS_LIGHT_OCR = "vision_plus_light_ocr"  # Fabric, material


PROCESSING_STRATEGY: dict[ImageLabel, ProcessingStrategy] = {
    ImageLabel.FOTO_PRODUCTO: ProcessingStrategy.VISION_ONLY,
    ImageLabel.FOTO_INSTALACION: ProcessingStrategy.VISION_ONLY,
    ImageLabel.MUESTRA_MATERIAL: ProcessingStrategy.VISION_PLUS_LIGHT_OCR,
    ImageLabel.CROQUIS_MEDICION: ProcessingStrategy.OCR_PLUS_VISION,
    ImageLabel.PLANO_TECNICO: ProcessingStrategy.OCR_PLUS_VISION,
    ImageLabel.DOCUMENTO_FOTOGRAFIADO: ProcessingStrategy.OCR_FIRST,
    ImageLabel.COMPROBANTE_PAGO: ProcessingStrategy.OCR_FIRST,
    ImageLabel.INCIDENCIA: ProcessingStrategy.VISION_PLUS_LIGHT_OCR,
    ImageLabel.RENDER: ProcessingStrategy.VISION_ONLY,
    ImageLabel.CAPTURA_PANTALLA: ProcessingStrategy.OCR_FIRST,
    ImageLabel.LOGO_GRAFICO: ProcessingStrategy.VISION_ONLY,
    ImageLabel.DESCONOCIDO: ProcessingStrategy.OCR_PLUS_VISION,
}


def classify_by_filename(filename: str) -> list[tuple[ImageLabel, float]]:
    """Classify an image by its filename keywords.

    Returns list of (label, confidence) sorted by confidence desc.
    """
    name_lower = filename.lower()
    results: list[tuple[ImageLabel, float]] = []
    for label, keywords in LABEL_KEYWORDS.items():
        matches = sum(1 for kw in keywords if kw in name_lower)
        if matches > 0:
            conf = min(0.3 + matches * 0.15, 0.9)
            results.append((label, conf))
    results.sort(key=lambda x: x[1], reverse=True)
    return results


def classify_by_folder(folder_path: str) -> list[tuple[ImageLabel, float]]:
    """Classify by folder path hints."""
    path_lower = folder_path.lower().replace("\\", "/")
    results: list[tuple[ImageLabel, float]] = []
    for pattern, label in FOLDER_LABEL_MAP.items():
        if pattern in path_lower:
            results.append((label, 0.6))
    return results


def get_processing_strategy(labels: list[ImageLabel]) -> ProcessingStrategy:
    """Determine the processing strategy from a set of labels."""
    if not labels:
        return ProcessingStrategy.OCR_PLUS_VISION
    # Priority: OCR_FIRST > OCR_PLUS_VISION > VISION_PLUS_LIGHT_OCR > VISION_ONLY
    strategies = [
        PROCESSING_STRATEGY.get(label, ProcessingStrategy.OCR_PLUS_VISION) for label in labels
    ]
    if ProcessingStrategy.OCR_FIRST in strategies:
        return ProcessingStrategy.OCR_FIRST
    if ProcessingStrategy.OCR_PLUS_VISION in strategies:
        return ProcessingStrategy.OCR_PLUS_VISION
    if ProcessingStrategy.VISION_PLUS_LIGHT_OCR in strategies:
        return ProcessingStrategy.VISION_PLUS_LIGHT_OCR
    return ProcessingStrategy.VISION_ONLY
