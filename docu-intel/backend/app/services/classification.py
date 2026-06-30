from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class ClassificationResult:
    document_type: str
    confidence: float
    matched_rules: list[str]


@dataclass(frozen=True)
class LearnedRule:
    """A rule produced by the learning loop, applied BEFORE the built-in RULES."""

    pattern_value: str
    target_class: str
    confidence: float = 0.0
    source: str = "learned"


RULES: dict[str, list[str]] = {
    "presupuesto": [
        "presupuesto",
        "oferta",
        "nº presupuesto",
        "no presupuesto",
        "total presupuesto",
        "cliente",
        "validez",
    ],
    "pedido": ["pedido", "orden de compra", "proveedor", "fecha pedido", "referencia pedido"],
    "factura": ["factura", "nº factura", "no factura", "base imponible", "iva", "total factura"],
    "albaran": ["albaran", "albarán", "entrega", "recibido", "mercancia", "mercancía"],
    "plano": [
        "escala",
        "planta",
        "seccion",
        "sección",
        "alzado",
        "cotas",
        "m²",
        "m2",
        "simbolos de plano",
        "símbolos de plano",
    ],
    "contrato": ["contrato", "clausula", "cláusula", "firmado por", "partes"],
    "email_exportado": ["from:", "to:", "subject:", "asunto:", "enviado:"],
}

FOLDER_HINTS = {
    "presupuestos": "presupuesto",
    "pedidos": "pedido",
    "facturas": "factura",
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

LEARNED_CONFIDENCE_BOOST = 0.5


def classify_document(
    filename: str,
    source_path: str | None,
    text: str,
    learned_rules: Iterable[LearnedRule] | None = None,
) -> ClassificationResult:
    normalized_filename = _normalize(filename)
    normalized_path = _normalize(source_path or "")
    normalized_text = _normalize(text)
    extension = PurePosixPath(filename.lower()).suffix

    scores: dict[str, float] = {}
    matches: dict[str, list[str]] = {}

    # Learned rules first (higher priority)
    for rule in learned_rules or []:
        pattern_norm = _normalize(rule.pattern_value)
        if not pattern_norm:
            continue
        if pattern_norm in normalized_filename or pattern_norm in normalized_text:
            scores[rule.target_class] = scores.get(rule.target_class, 0) + LEARNED_CONFIDENCE_BOOST
            matches.setdefault(rule.target_class, []).append(f"learned:{rule.pattern_value}")

    if extension in EXTENSION_HINTS:
        doc_type = EXTENSION_HINTS[extension]
        scores[doc_type] = scores.get(doc_type, 0) + 0.55
        matches.setdefault(doc_type, []).append(f"extension:{extension}")

    for folder, doc_type in FOLDER_HINTS.items():
        if re.search(rf"(^|/|\\){re.escape(folder)}($|/|\\)", normalized_path):
            scores[doc_type] = scores.get(doc_type, 0) + 0.65
            matches.setdefault(doc_type, []).append(f"folder:{folder}")

    if re.search(r"(^|/|\\)planos($|/|\\)", normalized_path) and _has_strong_plan_signal(
        normalized_filename,
        normalized_text,
        extension,
    ):
        scores["plano"] = scores.get("plano", 0) + 0.65
        matches.setdefault("plano", []).append("folder:planos")

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
    return " ".join(
        value.lower()
        .replace("\\", "/")
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )


def _has_strong_plan_signal(filename: str, text: str, extension: str) -> bool:
    if re.search(r"\b(plano|planta|alzado|seccion|secci[oó]n|cotas?)\b", filename):
        return True
    if re.search(r"\bescala\s*[:\-]?\s*1\s*[:/]\s*\d{1,5}\b", text):
        return True
    if extension in EXTENSION_HINTS:
        return False
    signals = {
        keyword
        for keyword in ("plano", "planta", "alzado", "seccion", "sección", "cota", "cotas", "m2")
        if keyword in text
    }
    return len(signals) >= 3
