"""MiniMax M3 — multi-dimensional classification helpers.

This module is the FASE 2 entry point. It produces three orthogonal
labels for a single document and explains which signal won for each:

* ``source_format``    — physical file format (email, spreadsheet,
                          word, pdf, image, dxf, unknown). Determined
                          from extension, MIME and parser signature.
* ``document_type``    — business type (presupuesto, pedido, albaran,
                          ...). Inherited from the existing rule
                          engine in :mod:`app.services.classification`.
* ``document_subtype`` — variant of the business type (firmado,
                          aceptado, proveedor, entrega, recogida, ...).
* ``content_tags``     — multi-valued list of descriptive tags.

The function is intentionally side-effect free: it does NOT persist
anything, does NOT call the LLM, does NOT touch the embedding index.
The caller decides whether the labels are applied to the document
and whether to record a classification_evidence JSON.

The result keeps every winning signal so the audit trail in
``Document.classification_evidence`` can be regenerated from the
return value without re-running the classifier.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.services.classification import (
    ClassificationResult,
    LearnedRule,
    classify_document,
)


# ---------------------------------------------------------------------------
# Bounded source_format vocabulary
# ---------------------------------------------------------------------------

SOURCE_FORMATS: tuple[str, ...] = (
    "email",
    "spreadsheet",
    "word",
    "pdf",
    "image",
    "dxf",
    "text",
    "unknown",
)


_EXTENSION_TO_FORMAT: dict[str, str] = {
    ".msg": "email",
    ".eml": "email",
    ".xlsx": "spreadsheet",
    ".xls": "spreadsheet",
    ".xlsm": "spreadsheet",
    ".csv": "spreadsheet",
    ".tsv": "spreadsheet",
    ".ods": "spreadsheet",
    ".docx": "word",
    ".doc": "word",
    ".odt": "word",
    ".rtf": "word",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tif": "image",
    ".tiff": "image",
    ".bmp": "image",
    ".gif": "image",
    ".webp": "image",
    ".dxf": "dxf",
    ".txt": "text",
    ".md": "text",
    ".json": "text",
    ".xml": "text",
}


# ---------------------------------------------------------------------------
# Subtype and content-tag vocabularies (bounded)
# ---------------------------------------------------------------------------

# Subtype extraction is conservative: we only assign a subtype when
# the filename or text contains a clear marker. The list is kept
# short to bound the cardinality of the column.
SUBTYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("firmado", ("firmado", "rubricado", "signing", "signed")),
    ("aceptado", ("aceptado", "acepta", "ok", "conforme", "confirmado", "accepted")),
    ("rechazado", ("rechazado", "denegado", "no aceptado", "rejected")),
    ("proveedor", ("proveedor", "supplier", "vendor")),
    ("cliente", ("cliente", "customer")),
    ("entrega", ("entrega", "delivery", "shipping")),
    ("recogida", ("recogida", "pickup", "pick-up", "collection")),
    ("instalacion", ("instalacion", "instalación", "installation", "montaje")),
    ("parcial", ("parcial", "partial")),
    ("rectificativa", ("rectificativa", "rectification", "abono")),
    (
        "con_descuento",
        ("con descuento", "con dto", "dto aplicado", "discount", "rebaja"),
    ),
    (
        "sin_descuento",
        ("sin descuento", "sin dto", "precio tarifa", "list price"),
    ),
    ("minibares", ("minibar", "minibares", "mini-bar")),
    ("cabeceros", ("cabecero", "cabeceros", "headboard")),
    ("traseras", ("trasera", "traseras", "back panel", "tras")),
    ("puertas", ("puerta", "puertas", "door", "doors")),
)


_CONTENT_TAG_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("carpinteria", ("carpinteria", "carpintería", "carpentry", "woodwork")),
    ("mobiliario", ("mueble", "muebles", "mobiliario", "furniture")),
    ("plano", ("plano", "planta", "alzado", "escala", "cota", "cotas")),
    ("fotografias", ("foto", "fotos", "fotografia", "fotografías", "image")),
    (
        "hostal-anibal",
        ("hostal anibal", "hostal-anibal", "hostal aníbal", "anibal"),
    ),
    ("ibiza", ("ibiza",)),
    ("medicion", ("medicion", "medición", "medida", "medidas", "mediciones")),
    ("incidencia", ("incidencia", "incidencias", "issue", "problema")),
    ("obra", ("obra", "obras", "construction site", "project")),
    ("presupuesto", ("presupuesto", "oferta", "cotizacion", "cotización")),
    (
        "hoja-confeccion",
        ("hoja de confeccion", "hoja de confección", "hoja confeccion"),
    ),
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceFormatDecision:
    """A single layer's vote for the source format."""

    layer: str  # extension | mime | parser | filename
    value: str
    weight: float


@dataclass(frozen=True)
class MultiDimClassification:
    """The full output of a single classification pass.

    ``source_format`` is always populated; ``document_type`` may be
    ``"desconocido"`` when no signal wins. ``document_subtype`` and
    ``content_tags`` default to empty so the database columns are
    always valid.
    """

    source_format: str
    document_type: str
    document_subtype: str | None
    content_tags: list[str]
    confidence: float
    classifier_version: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_persistence_dict(self) -> dict[str, Any]:
        """Return a dict ready to merge into ``Document`` columns."""
        return {
            "source_format": self.source_format,
            "document_type": self.document_type,
            "document_subtype": self.document_subtype,
            "content_tags": list(self.content_tags),
            "classification_evidence": dict(self.evidence),
            "classifier_version": self.classifier_version,
        }


# ---------------------------------------------------------------------------
# Source format detection
# ---------------------------------------------------------------------------


def detect_source_format(
    *,
    filename: str | None,
    mime_type: str | None,
    parser_signature: str | None = None,
) -> tuple[str, list[SourceFormatDecision]]:
    """Resolve the physical format of a document.

    The function is layered: extension, MIME and parser signal each
    cast a bounded vote, and the highest-weight vote wins. The list
    of decisions is returned so the caller can record every signal
    in ``classification_evidence``.

    ``parser_signature`` is a short string such as ``"pymupdf"``,
    ``"openpyxl"``, ``"extract_msg"``, ``"python-docx"`` or
    ``"tesseract"`` that the parser reports after opening the file.
    """
    decisions: list[SourceFormatDecision] = []

    if filename:
        ext = ""
        if "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower()
        if ext in _EXTENSION_TO_FORMAT:
            decisions.append(
                SourceFormatDecision(
                    layer="extension",
                    value=_EXTENSION_TO_FORMAT[ext],
                    weight=0.6,
                )
            )

    if mime_type:
        normalised = mime_type.split(";")[0].strip().lower()
        if normalised.startswith("application/vnd.ms-outlook") or normalised in {
            "message/rfc822",
            "text/x-eml",
        }:
            decisions.append(
                SourceFormatDecision("mime", "email", 0.7)
            )
        elif normalised in {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
            "text/csv",
            "text/tab-separated-values",
        }:
            decisions.append(SourceFormatDecision("mime", "spreadsheet", 0.7))
        elif normalised in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
            "application/rtf",
        }:
            decisions.append(SourceFormatDecision("mime", "word", 0.7))
        elif normalised == "application/pdf":
            decisions.append(SourceFormatDecision("mime", "pdf", 0.7))
        elif normalised.startswith("image/"):
            decisions.append(SourceFormatDecision("mime", "image", 0.7))
        elif normalised == "image/vnd.dxf":
            decisions.append(SourceFormatDecision("mime", "dxf", 0.7))

    if parser_signature:
        sig = parser_signature.lower().strip()
        # Map the parser name to a source_format. Keep the weight
        # below the extension so a wrong extension on a renamed
        # file does not override the parser's own verdict.
        if sig in {"pymupdf", "pdfplumber", "pypdf", "tika_pdf"}:
            decisions.append(SourceFormatDecision("parser", "pdf", 0.8))
        elif sig in {"openpyxl", "xlrd", "pyexcel", "pandas"}:
            decisions.append(SourceFormatDecision("parser", "spreadsheet", 0.8))
        elif sig in {"python-docx", "docx2txt", "antiword"}:
            decisions.append(SourceFormatDecision("parser", "word", 0.8))
        elif sig in {"extract_msg", "email", "eml-parser"}:
            decisions.append(SourceFormatDecision("parser", "email", 0.8))
        elif sig in {"tesseract", "paddleocr", "vlm", "easyocr"}:
            decisions.append(SourceFormatDecision("parser", "image", 0.5))
        elif sig in {"ezdxf", "dxf-parser"}:
            decisions.append(SourceFormatDecision("parser", "dxf", 0.8))

    if not decisions:
        return ("unknown", [])

    # Aggregate by value with weight, then keep the highest.
    totals: dict[str, float] = {}
    for d in decisions:
        totals[d.value] = totals.get(d.value, 0.0) + d.weight
    winner_value = max(totals, key=lambda v: totals[v])
    return (winner_value, decisions)


# ---------------------------------------------------------------------------
# Subtype + content tags
# ---------------------------------------------------------------------------


def _match_any(haystack: str, needles: Iterable[str]) -> str | None:
    if not haystack:
        return None
    for needle in needles:
        if needle in haystack:
            return needle
    return None


def detect_subtype(filename: str | None, text: str | None) -> str | None:
    """Return a subtype label or ``None`` if no signal wins.

    The function only inspects the lowercase text, so the caller must
    pass the same string the rule engine will see.
    """
    haystack = " ".join(
        part for part in (filename or "", text or "") if part
    ).lower()
    if not haystack:
        return None
    for label, keywords in SUBTYPE_RULES:
        if _match_any(haystack, keywords):
            return label
    return None


def detect_content_tags(
    filename: str | None,
    text: str | None,
    *,
    max_tags: int = 8,
) -> list[str]:
    """Return a deduplicated list of content tags ordered by first hit."""
    haystack = " ".join(
        part for part in (filename or "", text or "") if part
    ).lower()
    if not haystack:
        return []
    seen: set[str] = set()
    tags: list[str] = []
    for label, keywords in _CONTENT_TAG_RULES:
        if len(tags) >= max_tags:
            break
        if label in seen:
            continue
        if _match_any(haystack, keywords):
            tags.append(label)
            seen.add(label)
    return tags


# ---------------------------------------------------------------------------
# Combined classifier
# ---------------------------------------------------------------------------


CLASSIFIER_VERSION = "minimax-m3-1.0.0"


def classify_multidim(
    *,
    filename: str | None,
    source_path: str | None,
    mime_type: str | None,
    parser_signature: str | None,
    text: str,
    learned_rules: Iterable[LearnedRule] | None = None,
    content_route: str | None = None,
) -> MultiDimClassification:
    """Compute the full multi-dimensional classification for one document.

    The function is a thin orchestrator over the existing
    :func:`app.services.classification.classify_document` and the new
    helpers in this module. It returns a :class:`MultiDimClassification`
    that the caller can persist as-is.
    """
    source_format, decisions = detect_source_format(
        filename=filename,
        mime_type=mime_type,
        parser_signature=parser_signature,
    )

    business: ClassificationResult = classify_document(
        filename=filename or "",
        source_path=source_path,
        text=text,
        learned_rules=learned_rules,
        content_route=content_route,
    )

    subtype = detect_subtype(filename, text)
    tags = detect_content_tags(filename, text)

    # The dimension evidence explains which signal won. The label set
    # is bounded (no filenames, no IDs, no document text) so the JSON
    # can be cached in metrics labels without leaking PII.
    evidence: dict[str, Any] = {
        "source_format": {
            "winner": source_format,
            "votes": [
                {"layer": d.layer, "value": d.value, "weight": d.weight}
                for d in decisions
            ],
        },
        "document_type": {
            "winner": business.document_type,
            "confidence": business.confidence,
            "matched_rules": list(business.matched_rules),
        },
        "document_subtype": subtype,
        "content_tags": list(tags),
    }
    if source_format == "email" and business.document_type in {
        "desconocido",
        "foto_producto",
    }:
        # FASE 2 sanity: a .msg/.eml is never a product photo. The
        # rule engine should have caught this already, but if it
        # did not, force the type to email_exportado and lower the
        # subtype bias toward communication-related tags.
        evidence["document_type"]["forced"] = True
        business = ClassificationResult(
            document_type="email_exportado",
            confidence=max(business.confidence, 0.9),
            matched_rules=list(business.matched_rules) + ["format_lock:email"],
        )

    return MultiDimClassification(
        source_format=source_format,
        document_type=business.document_type,
        document_subtype=subtype,
        content_tags=tags,
        confidence=business.confidence,
        classifier_version=CLASSIFIER_VERSION,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


def extraction_fingerprint(
    *,
    text_hash: str,
    document_type: str,
    classifier_version: str,
    provider: str,
    model: str,
    prompt_version: str,
    schema_version: str,
    extractor_version: str,
) -> str:
    """Compute the idempotence fingerprint for an extraction.

    The fingerprint is a SHA-256 of a fixed-width concatenation; the
    ordering is significant and any caller that omits a field will
    produce a different hash, which is what we want.
    """
    components = [
        text_hash,
        document_type,
        classifier_version,
        provider,
        model,
        prompt_version,
        schema_version,
        extractor_version,
    ]
    payload = "\u0001".join(components).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


_TEXT_HASH_RE = re.compile(r"\s+")


def hash_text_for_fingerprint(text: str | None) -> str:
    """Normalise text whitespace and return a short stable hash.

    The hash is only used to detect "the document has changed" — it
    is NOT a security identifier. We keep the cheap version here so
    the function is fast to call on every extraction candidate.
    """
    if not text:
        return ""
    normalised = _TEXT_HASH_RE.sub(" ", text).strip().lower()
    return hashlib.sha256(normalised.encode("utf-8", errors="ignore")).hexdigest()
