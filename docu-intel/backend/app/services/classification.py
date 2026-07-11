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
        # Sinónimos (mismo documento, OCR a menudo ilegible -> usamos el nombre)
        "hoja confeccion",
        "hojas confeccion",
        "hoja tapiceria",
        "hojas tapiceria",
        "orden confeccion",
        "ordenes confeccion",
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
        # Por nombre de archivo (texto OCR a menudo ilegible)
        "plano",
        "layout",
        "planta",
        "aperturas",
    ],
    "contrato": ["contrato", "clausula", "cláusula", "firmado por", "partes"],
    "email_exportado": ["from:", "to:", "subject:", "asunto:", "enviado:"],
    # --- NUEVOS: tipos de imagen (interiorismo/decoración) ---
    "foto_producto": [
        "cortina", "cortinas", "mueble", "muebles", "sillon",
        "sofa", "mesa", "silla", "sillas", "armario", "cocina", "bano",
        "dormitorio", "salon", "comedor", "terraza", "persiana", "persianas",
        "toldo", "toldos", "banderola", "panel", "paneles", "tapizado",
    ],
    "muestra_tela": [
        "tela", "telas", "visillo", "visillos", "forro", "forros",
        "lino", "algodon", "poliester", "muestra", "muestras",
        "colchoneta", "colchonetas", "felpudo", "moqueta", "alfombra",
    ],
    "croquis_medida": [
        "croquis", "medida", "medidas", "medicion",
        "ancho", "largo", "alto", "caida", "cadam", "rosca",
        "bastidor", "barra", "guia", "medicion por incidencia",
    ],
    # --- NUEVOS: tipos de documento administrativo ---
    "comprobante_pago": [
        "comprobante", "comprobante de pago", "pago", "sepa",
        "transferencia", "recibo", "justificante", "banca a distancia",
        "servicio de banca", "cargo", "abono",
    ],
    "dua": [
        "dua", "aduana", "aduanero", "despacho", "circuito verde",
        "export", "d export", "documentoa unico aduanero",
    ],
    "albaran_transporte": [
        "pop", "recogida", "mbe", "ups", "dhl", "envio",
        "transporte", "etiqueta", "entrega ups",
        "mail boxes", "mailbox",
        # Sinónimos de documento de carga/transporte
        "packing", "box palet", "pod", "palet", "albaran",
    ],
    # --- NUEVOS: fichas técnicas / certificados ---
    "ficha_tecnica": [
        "ficha tecnica", "ficha técnica", "datasheet", "data sheet",
        "certificate", "certificado", "certificacion", "technical data",
        "ficha", "sgibe",
    ],
    # --- NUEVOS: tarifas / listas de precios ---
    "tarifa": [
        "precios", "tarifa", "tarifas", "price list", "lista precios",
        "lista de precios", "catalogo precios",
    ],
    # --- NUEVOS: proformas / confirmaciones de pedido (sinónimos) ---
    "proforma": [
        "proforma", "conferma d'ordine", "conferma ordine", "conferma",
        "confirmacion de pedido", "confirmacion pedido",
        "confirmacion de compra", "pro forma",
    ],
    # --- NUEVOS: manuales / instrucciones de uso ---
    "instrucciones": [
        "instruccion", "instrucciones", "mantenimiento",
        "manual de", "manual", "modo de empleo", "ficha instrucciones",
    ],
    # --- NUEVOS: renders / imágenes 3D de interiores ---
    "render": [
        "render", "conceptrender", "concept render", "render 3d",
        "visualizacion", "vista 3d",
    ],
    # --- PM1.1: Tipos documentales técnicos de obra ---
    "plano_arquitectura": [
        "plano arquitectura", "planta", "alzado", "seccion",
        "corte", "detalle constructivo", "emplazamiento",
        "escala", "cotas",  # Shared with generic "plano"
    ],
    "plano_estructura": [
        "plano estructura", "estructura", "hormigon", "hormigón",
        "acero", "armadura", "cimentacion", "cimentación",
        "forjado", "viga", "columna", "sobrecimiento",
        "escala", "cotas",  # Shared with generic "plano"
        "seccion constructiva", "corte constructivo",  # Structural sections
        "muro exterior", "tabique", "aislamiento",  # Construction details
    ],
    "plano_electrico": [
        "plano electrico", "eléctrico", "electricidad",
        "toma de corriente", "interruptor", "cuadro electrico",
        "linea electrica", "cableado", "instalacion electrica",
    ],
    "plano_fontaneria": [
        "plano fontaneria", "fontanería", "sanitario",
        "tuberia", "tubería", "agua fria", "agua caliente",
        "alcantarillado", "desague", "desagüe",
    ],
    "plano_climatizacion": [
        "plano climatizacion", "climatización", "aire acondicionado",
        "calefaccion", "calefacción", "ventilacion", "ventilación",
        "hvac", "tuberia refrigerante",
    ],
    "plano_contra_incendios": [
        "plano contra incendios", "contra incendios", "proteccion pasiva",
        "reaccion al fuego", "resistencia al fuego",
        "extintor", "bomba de incendios", "senalizacion",
    ],
    "croquis_medicion": [
        "croquis medicion", "croquis de medicion", "mediciones",
        "medidas", "superficies", "cuadro de superficies",
    ],
    "memoria_descriptiva": [
        "memoria descriptiva", "descripcion de obra",
        "objeto de la obra", "descripcion del proyecto",
    ],
    "memoria_constructiva": [
        "memoria constructiva", "solucion constructiva",
        "descripcion constructiva", "proceso de ejecucion",
        "metodo de obra", "condiciones de ejecucion",
    ],
    "pliego_condiciones": [
        "pliego de condiciones", "pliego tecnico",
        "pliego administrativo", "clausulas administrativas",
        "clausulas tecnicas", "prescripciones tecnicas",
        "condiciones generales", "condiciones particulares",
    ],
    "mediciones_obra": [
        "mediciones de obra", "cuadro de mediciones",
        "medicion por partidas", "computation de metricos",
        "c metros", "metricas", "certificacion de obra",
    ],
    "estudio_seguridad": [
        "estudio de seguridad", "plan de seguridad",
        "evaluacion de riesgos", "epi", "proteccion colectiva",
        "seguridad en obra", "coordinador de seguridad",
    ],
    "gestion_residuos": [
        "gestion de residuos", "plan de residuos",
        "residuos de construccion", "rasa", "reciclaje",
        "eliminacion de residuos",
    ],
    "manual_instalacion": [
        "manual de instalacion", "manual de instalación",
        "instrucciones de montaje", "guia de instalacion",
        "procedimiento de instalacion",
    ],
}

# Keywords that need word-boundary matching (avoid "cota" → "mascota")
WORD_BOUNDARY_KEYWORDS = {
    "presupuesto", "oferta", "pedido", "factura", "albaran", "albarán",
    "escala", "alzado", "cota", "cotas", "contrato", "clausula", "cláusula",
    "planta", "seccion", "sección", "montaje", "costura", "patron", "patrón",
    "tela", "muestra", "total",
    # --- NUEVOS ---
    "pago", "pop", "dua", "ups", "mbe", "envio", "envío",
    "recogida", "transporte", "comprobante", "aduana", "sepa",
    "transferencia", "recibo", "croquis", "medida",
    # --- NUEVOS (expansión de diccionario) ---
    "precios", "tarifa", "pod", "proforma", "render", "manual",
    "certificado", "ficha", "layout", "aperturas", "packing",
    "palet", "instruccion", "mantenimiento",
    # --- PM1.1: Tipos técnicos ---
    "estructura", "hormigon", "electricidad", "fontaneria",
    "climatizacion", "incendios", "memoria", "pliego",
    "mediciones", "seguridad", "residuos", "instalacion",
}

FOLDER_HINTS = {
    "presupuestos": "presupuesto",
    "pedidos": "pedido",
    "facturas": "factura",
    "imagenes": "foto_producto",     # --- CAMBIO: era "imagen" ---
    "telas": "muestra_tela",          # --- NUEVO ---
    "muestras": "muestra_tela",       # --- NUEVO ---
    "croquis": "croquis_medida",      # --- NUEVO ---
    # --- PM1.1: Carpetas técnicas de obra ---
    "planos": "plano",
    "planos_arquitectura": "plano_arquitectura",
    "planos_estructura": "plano_estructura",
    "planos_electricos": "plano_electrico",
    "planos_fontaneria": "plano_fontaneria",
    "planos_climatizacion": "plano_climatizacion",
    "planos_contra_incendios": "plano_contra_incendios",
    "memorias": "memoria_descriptiva",
    "memoria_constructiva": "memoria_constructiva",
    "pliegos": "pliego_condiciones",
    "mediciones": "mediciones_obra",
    "presupuestos_obra": "mediciones_obra",
    "seguridad": "estudio_seguridad",
    "residuos": "gestion_residuos",
    "fichas_tecnicas": "ficha_tecnica",
    "manuales": "manual_instalacion",
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
    content_route: str | None = None,  # --- NUEVO ---
) -> ClassificationResult:
    normalized_filename = _normalize(filename)
    normalized_path = _normalize(source_path or "")
    normalized_text = _normalize(text)
    extension = PurePosixPath(filename.lower()).suffix
    is_image = extension in IMAGE_EXTENSIONS

    scores: dict[str, float] = {}
    matches: dict[str, list[str]] = {}
    matched_keywords: dict[str, set[str]] = {}  # dedup per type

    # --- Phase 0: Image subtypes from content_route (highest priority) ---
    # El content_router ya detectó si es foto de interiorismo/tela usando CLIP
    # + keywords + carpeta. Esa señal es muy fiable (conf 0.7+), la respetamos.
    if content_route in ("interior_design", "fabric_description"):
        if content_route == "fabric_description":
            scores["muestra_tela"] = 0.85
            matches["muestra_tela"] = [f"content_route:{content_route}"]
        else:
            # interior_design: distinguir croquis (con medidas) de foto simple
            croquis_signals = sum(
                1 for kw in ("croquis", "medida", "medidas", "medicion", "cota", "cotas")
                if _match_keyword(_normalize(kw), normalized_text)
                or _match_keyword(_normalize(kw), normalized_filename)
            )
            if croquis_signals >= 2:
                scores["croquis_medida"] = 0.85
                matches["croquis_medida"] = [f"content_route:{content_route}+medidas"]
            else:
                scores["foto_producto"] = 0.85
                matches["foto_producto"] = [f"content_route:{content_route}"]

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
    # signals. Two acceptable cases:
    #   (a) filename signal + >=2 text signals (the original strict rule:
    #       a scanned plan whose OCR yielded plan-like vocabulary), OR
    #   (b) >=2 filename signals + the file lives in a ``planos/`` folder
    #       (a scanned plan whose OCR yielded nothing — text="" — but whose
    #       name is unambiguous, e.g. "plano_planta_baja.jpg"). Without this
    #       branch every scanned plan with a blank OCR was misclassified as
    #       "imagen" and lost.
    if is_image and scores.get("plano", 0) > 0:
        plan_filename_kws = (
            "plano", "planta", "alzado", "seccion", "sección", "cotas",
        )
        filename_signals = sum(
            1 for kw in plan_filename_kws if _match_keyword(kw, normalized_filename)
        )
        has_filename_signal = filename_signals >= 1
        text_signals = sum(
            1 for kw in ("plano", "planta", "alzado", "seccion", "sección", "cota", "cotas", "m2")
            if _match_keyword(kw, normalized_text)
        )
        in_planos_folder = bool(re.search(r"(^|/|\\)planos($|/|\\)", normalized_path))
        strong_filename_case = filename_signals >= 2 and in_planos_folder
        if not ((has_filename_signal and text_signals >= 2) or strong_filename_case):
            # Suppress plano classification for images without strong signals
            scores.pop("plano", None)
            matches.pop("plano", None)

    # --- Phase 7: Cross-validation — if folder says X but text strongly says Y ---
    # If text has 3+ keyword matches for a different type, boost that type
    # to potentially override the folder hint.
    for doc_type, kws in matched_keywords.items():
        if len(kws) >= 3 and scores.get(doc_type, 0) > 0:
            scores[doc_type] = scores.get(doc_type, 0) + 0.15  # bonus for strong text signal

    # --- Phase 8: Prefer specific subtypes over generic "plano" ---
    # PM1.1: When a specific plan subtype (plano_estructura, plano_electrico, etc.)
    # has a reasonable score, prefer it over the generic "plano" classification.
    # This ensures technical documents get properly categorized while still
    # falling back to "plano" when no specific subtype matches strongly.
    _PLAN_SUBTYPES = {
        "plano_arquitectura", "plano_estructura", "plano_electrico",
        "plano_fontaneria", "plano_climatizacion", "plano_contra_incendios",
    }
    if "plano" in scores:
        plano_score = scores["plano"]
        # Find the best specific subtype
        best_subtype = None
        best_subtype_score = 0
        for subtype in _PLAN_SUBTYPES:
            if subtype in scores and scores[subtype] > best_subtype_score:
                best_subtype = subtype
                best_subtype_score = scores[subtype]
        # If a specific subtype has >= 2 keyword matches and a reasonable score,
        # boost it to win over generic "plano" (which may have folder bonus)
        if best_subtype and best_subtype_score >= 0.50:
            # Boost enough to beat the generic "plano" (which may have folder bonus)
            scores[best_subtype] = best_subtype_score + 1.20

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
