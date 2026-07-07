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


# ---------------------------------------------------------------------------
# RULES — keyword lists per document type
#
# Scoring:
#   - Filename match: +0.35 (deduplicated per keyword)
#   - Text match: +0.25 (deduplicated per keyword, word-boundary)
#   - Folder hint: +0.55 (reduced from 0.65 to not dominate over text content)
#   - Extension hint: +0.50
#   - Learned rule: +0.40
#   - Plan detection: +0.55 (with strong signal requirement)
# ---------------------------------------------------------------------------
RULES: dict[str, list[str]] = {
    "presupuesto": [
        "presupuesto",
        "oferta",
        "nº presupuesto",
        "no presupuesto",
        "total presupuesto",
        "validez",
    ],
    "pedido": ["pedido", "orden de compra", "fecha pedido", "referencia pedido"],
    "factura": ["factura", "nº factura", "no factura", "base imponible", "iva", "total factura"],
    "albaran": ["albaran", "albarán", "entrega", "recibido", "mercancia", "mercancía"],
    "hoja_confeccion": [
        "hoja de confeccion",
        "hoja de confección",
        "instrucciones de confeccion",
        "instrucciones de confección",
        "proceso de confeccion",
        "proceso de confección",
        "montaje",
        "costura",
        "patron",
        "patrón",
        "tela",
        "muestra",
    ],
    "plano": [
        "escala",
        "alzado",
        "cotas",
        "simbolos de plano",
        "símbolos de plano",
    ],
    "contrato": ["contrato", "clausula", "cláusula", "firmado por", "partes"],
    "email_exportado": ["from:", "to:", "subject:", "asunto:", "enviado:"],
}

# Keywords that need word-boundary matching (avoid "cota" → "mascota")
WORD_BOUNDARY_KEYWORDS = {
    "presupuesto", "oferta", "pedido", "factura", "albaran", "albarán",
    "escala", "alzado", "cota", "cotas", "contrato", "clausula", "cláusula",
    "planta", "seccion", "sección", "montaje", "costura", "patron", "patrón",
    "tela", "muestra", "total",
}

FOLDER_HINTS = {
    "presupuestos": "presupuesto",
    "pedidos": "pedido",
    "facturas": "factura",
    "imagenes": "imagen",
}

# Image extensions that should NEVER be classified as "plano" unless
# there's a very strong signal (filename + multiple text signals).
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

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

LEARNED_CONFIDENCE_BOOST = 0.40


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
    is_image = extension in IMAGE_EXTENSIONS

    scores: dict[str, float] = {}
    matches: dict[str, list[str]] = {}
    matched_keywords: dict[str, set[str]] = {}  # dedup per type

    # --- Phase 1: Learned rules (highest priority) ---
    for rule in learned_rules or []:
        pattern_norm = _normalize(rule.pattern_value)
        if not pattern_norm:
            continue
        if _match_keyword(pattern_norm, normalized_filename) or _match_keyword(pattern_norm, normalized_text):
            scores[rule.target_class] = scores.get(rule.target_class, 0) + LEARNED_CONFIDENCE_BOOST
            matches.setdefault(rule.target_class, []).append(f"learned:{rule.pattern_value}")

    # --- Phase 2: Extension hint ---
    if extension in EXTENSION_HINTS:
        doc_type = EXTENSION_HINTS[extension]
        scores[doc_type] = scores.get(doc_type, 0) + 0.50
        matches.setdefault(doc_type, []).append(f"extension:{extension}")

    # --- Phase 3: Folder hint (reduced weight to not dominate over text) ---
    for folder, doc_type in FOLDER_HINTS.items():
        if re.search(rf"(^|/|\\){re.escape(folder)}($|/|\\)", normalized_path):
            scores[doc_type] = scores.get(doc_type, 0) + 0.55
            matches.setdefault(doc_type, []).append(f"folder:{folder}")

    # --- Phase 4: Plan detection (with image guard) ---
    if re.search(r"(^|/|\\)planos($|/|\\)", normalized_path) and _has_strong_plan_signal(
        normalized_filename, normalized_text, extension,
    ):
        scores["plano"] = scores.get("plano", 0) + 0.55
        matches.setdefault("plano", []).append("folder:planos")

    # --- Phase 5: Keyword matching (deduplicated, word-boundary) ---
    for doc_type, keywords in RULES.items():
        for keyword in keywords:
            keyword_norm = _normalize(keyword)
            # Skip if this keyword already matched for this type
            if keyword_norm in matched_keywords.get(doc_type, set()):
                continue

            if _match_keyword(keyword_norm, normalized_filename):
                scores[doc_type] = scores.get(doc_type, 0) + 0.35
                matched_keywords.setdefault(doc_type, set()).add(keyword_norm)
                matches.setdefault(doc_type, []).append(f"filename:{keyword}")
            if _match_keyword(keyword_norm, normalized_text):
                scores[doc_type] = scores.get(doc_type, 0) + 0.25
                matched_keywords.setdefault(doc_type, set()).add(keyword_norm)
                matches.setdefault(doc_type, []).append(f"text:{keyword}")

    # --- Phase 6: Image guard — prevent JPEG scans from being "plano" ---
    # If the file is an image and "plano" is winning, require VERY strong
    # signals (filename match + 3+ text signals). Otherwise suppress plano.
    if is_image and scores.get("plano", 0) > 0:
        has_filename_signal = any(
            _match_keyword(kw, normalized_filename)
            for kw in ("plano", "planta", "alzado", "seccion", "sección", "cotas")
        )
        text_signals = sum(
            1 for kw in ("plano", "planta", "alzado", "seccion", "sección", "cota", "cotas", "m2")
            if _match_keyword(kw, normalized_text)
        )
        if not (has_filename_signal and text_signals >= 2):
            # Suppress plano classification for images without strong signals
            scores.pop("plano", None)
            matches.pop("plano", None)

    # --- Phase 7: Cross-validation — if folder says X but text strongly says Y ---
    # If text has 3+ keyword matches for a different type, boost that type
    # to potentially override the folder hint.
    for doc_type, kws in matched_keywords.items():
        if len(kws) >= 3 and scores.get(doc_type, 0) > 0:
            scores[doc_type] = scores.get(doc_type, 0) + 0.15  # bonus for strong text signal

    # --- Result ---
    if not scores:
        return ClassificationResult("desconocido", 0.2, [])

    doc_type, score = max(scores.items(), key=lambda item: item[1])
    confidence = min(0.98, max(0.4, score))
    return ClassificationResult(doc_type, confidence, matches.get(doc_type, []))


def _match_keyword(keyword: str, text: str) -> bool:
    """Match a keyword with word boundaries to avoid substring false positives.

    "cota" won't match "mascota", "planta" won't match "implantacion".
    Also handles Spanish plurals: "cota" matches "cotas", "factura" matches "facturas".
    """
    if keyword in WORD_BOUNDARY_KEYWORDS:
        # Match the keyword as a word, optionally followed by Spanish plural suffixes
        return bool(re.search(rf"\b{re.escape(keyword)}(es|s)?\b", text))
    # For multi-word keywords or short codes, use substring (they're specific enough)
    return keyword in text


def _normalize(value: str) -> str:
    return " ".join(
        value.lower()
        .replace("\\", "/")
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )


def _has_strong_plan_signal(filename: str, text: str, extension: str) -> bool:
    """Require strong evidence before classifying as plano.

    For images, we need filename match + text signals.
    For PDFs/text, standard signal detection applies.
    """
    if re.search(r"\b(plano|planta|alzado|seccion|secci[oó]n|cotas?)\b", filename):
        return True
    if re.search(r"\bescala\s*[:\-]?\s*1\s*[:/]\s*\d{1,5}\b", text):
        return True
    if extension in IMAGE_EXTENSIONS:
        # Images need stronger evidence
        signals = {
            kw for kw in ("plano", "planta", "alzado", "seccion", "sección", "cota", "cotas", "m2")
            if _match_keyword(kw, text)
        }
        return len(signals) >= 3
    # For text-based files, standard detection
    signals = {
        kw for kw in ("plano", "planta", "alzado", "seccion", "sección", "cota", "cotas", "m2")
        if _match_keyword(kw, text)
    }
    return len(signals) >= 3
