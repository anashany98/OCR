from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class ClassificationResult:
    document_type: str
    confidence: float
    matched_rules: list[str]


RULES: dict[str, list[str]] = {
    "presupuesto": ["presupuesto", "oferta", "nº presupuesto", "no presupuesto", "total presupuesto", "cliente", "validez"],
    "pedido": ["pedido", "orden de compra", "proveedor", "fecha pedido", "referencia pedido"],
    "factura": ["factura", "nº factura", "no factura", "base imponible", "iva", "total factura"],
    "albaran": ["albaran", "albarán", "entrega", "recibido", "mercancia", "mercancía"],
    "plano": ["escala", "planta", "seccion", "sección", "alzado", "cotas", "m²", "m2", "simbolos de plano", "símbolos de plano"],
    "contrato": ["contrato", "clausula", "cláusula", "firmado por", "partes"],
    "email_exportado": ["from:", "to:", "subject:", "asunto:", "enviado:"],
}

FOLDER_HINTS = {
    "presupuestos": "presupuesto",
    "pedidos": "pedido",
    "facturas": "factura",
    "planos": "plano",
    "imagenes": "imagen",
}

EXTENSION_HINTS = {
    ".xlsx": "excel",
    ".xls": "excel",
    ".csv": "excel",
    ".tsv": "excel",
    ".png": "imagen",
    ".jpg": "imagen",
    ".jpeg": "imagen",
    ".tif": "imagen",
    ".tiff": "imagen",
    ".bmp": "imagen",
}


def classify_document(filename: str, source_path: str | None, text: str) -> ClassificationResult:
    normalized_filename = _normalize(filename)
    normalized_path = _normalize(source_path or "")
    normalized_text = _normalize(text)
    extension = PurePosixPath(filename.lower()).suffix

    scores: dict[str, float] = {}
    matches: dict[str, list[str]] = {}

    if extension in EXTENSION_HINTS:
        doc_type = EXTENSION_HINTS[extension]
        scores[doc_type] = scores.get(doc_type, 0) + 0.55
        matches.setdefault(doc_type, []).append(f"extension:{extension}")

    for folder, doc_type in FOLDER_HINTS.items():
        if re.search(rf"(^|/|\\){re.escape(folder)}($|/|\\)", normalized_path):
            scores[doc_type] = scores.get(doc_type, 0) + 0.65
            matches.setdefault(doc_type, []).append(f"folder:{folder}")

    for doc_type, keywords in RULES.items():
        for keyword in keywords:
            keyword_norm = _normalize(keyword)
            if keyword_norm in normalized_filename:
                scores[doc_type] = scores.get(doc_type, 0) + 0.35
                matches.setdefault(doc_type, []).append(f"filename:{keyword}")
            if keyword_norm in normalized_text:
                scores[doc_type] = scores.get(doc_type, 0) + 0.25
                matches.setdefault(doc_type, []).append(f"text:{keyword}")

    if not scores:
        return ClassificationResult("desconocido", 0.2, [])

    doc_type, score = max(scores.items(), key=lambda item: item[1])
    confidence = min(0.98, max(0.4, score))
    return ClassificationResult(doc_type, confidence, matches.get(doc_type, []))


def _normalize(value: str) -> str:
    return " ".join(value.lower().replace("\\", "/").split())

