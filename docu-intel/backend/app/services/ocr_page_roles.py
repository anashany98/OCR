"""One policy for deciding when an OCR score is meaningful.

``document_pages`` also stores pages produced from native text (PDF, Office,
email, DXF) and embedded media such as logos.  Those pages are searchable, but
an OCR confidence is not a quality signal for them.  Keeping this distinction
in one module prevents queues, dashboards and quality evaluation from drifting.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql.elements import ColumnElement

NON_OCR_CONTENT_KINDS = frozenset({"native_text", "decorative", "photo"})
NATIVE_TEXT_ENGINES = frozenset(
    {
        "pymupdf",
        "plain_text",
        "extract-msg",
        "docx_parser",
        "pandas",
        "dxf_parser",
    }
)
_DECORATIVE_MARKERS = (
    "logotipo",
    "logo",
    "icono",
    "linkedin",
    "facebook",
    "instagram",
    "twitter",
    "plataforma profesional",
)
_BUSINESS_SIGNAL = re.compile(
    r"\d|€|\$|\b(?:pedido|factura|albaran|albarán|presupuesto|total|importe|referencia)\b",
    re.IGNORECASE,
)


def is_ocr_applicable(content_kind: str | None) -> bool:
    """Whether a page should participate in OCR-quality metrics."""
    return (content_kind or "").strip().lower() not in NON_OCR_CONTENT_KINDS


def ocr_applicable_clause(column: ColumnElement[str | None]) -> ColumnElement[bool]:
    """SQL predicate that keeps legacy pages until their role is backfilled."""
    return or_(column.is_(None), column.not_in(NON_OCR_CONTENT_KINDS))


def ocr_meets_threshold_clause(
    content_kind_column: ColumnElement[str | None],
    confidence_column: ColumnElement[float | None],
    threshold: float,
) -> ColumnElement[bool]:
    """Native/decorative pages pass a minimum-OCR filter by definition.

    Their text did not come from OCR, so treating ``NULL`` as failed OCR would
    hide reliable digital content from a search restricted to readable pages.
    """
    return or_(
        ~ocr_applicable_clause(content_kind_column),
        confidence_column >= threshold,
    )


def infer_ocr_content_kind(
    *,
    current_kind: str | None,
    ocr_engine: str | None,
    image_path: str | None,
    text: str | None,
    block_engines: Iterable[str | None] = (),
) -> str:
    """Infer a stable role for legacy and newly extracted pages.

    The function deliberately fails open to ``ocr``.  Only unequivocal native
    parser output and clearly decorative embedded media are excluded from OCR
    quality accounting.
    """
    normalized = (current_kind or "").strip().lower()
    if normalized:
        return normalized

    engines = {(ocr_engine or "").strip().lower()}
    engines.update((engine or "").strip().lower() for engine in block_engines)
    if "photo_skip" in engines:
        return "photo"
    if engines & NATIVE_TEXT_ENGINES:
        return "native_text"
    if is_probably_decorative_embedded_media(
        image_path=image_path,
        text=text,
    ):
        return "decorative"
    return "ocr"


def is_probably_decorative_embedded_media(*, image_path: str | None, text: str | None) -> bool:
    """Recognise inline logos/icons without discarding their searchable text.

    Embedded receipts, screenshots and plans must remain OCR-applicable.  A
    page is therefore considered decorative only when it is an embedded asset
    and it carries no number, amount, identifier or business keyword.
    """
    path = (image_path or "").replace("\\", "/").lower()
    if "/embedded/" not in path:
        return False
    clean = re.sub(
        r"^\s*\[imagen incrustada:[^\]]+\]\s*", "", text or "", flags=re.IGNORECASE
    ).strip()
    normalized = " ".join(clean.lower().split())
    if not normalized:
        return True
    if any(marker in normalized for marker in _DECORATIVE_MARKERS):
        return True
    if _BUSINESS_SIGNAL.search(normalized):
        return False
    return len(normalized) <= 80 and len(re.findall(r"[\wáéíóúñ]+", normalized)) <= 8


def backfill_ocr_page_roles(db: Session, *, dry_run: bool = False) -> dict[str, int]:
    """Reconcile legacy pages with the role policy without rerunning OCR.

    It is safe to run repeatedly.  Searchable text and immutable OCR attempts
    are preserved; non-applicable pages merely lose their misleading score and
    leave the review metrics.
    """
    from app.models import DocumentPage

    pages = list(
        db.scalars(
            select(DocumentPage).options(
                selectinload(DocumentPage.blocks),
                selectinload(DocumentPage.ocr_attempts),
            )
        ).all()
    )
    changed = 0
    native = 0
    decorative = 0
    photo = 0
    for page in pages:
        content_kind = infer_ocr_content_kind(
            current_kind=page.ocr_content_kind,
            ocr_engine=page.ocr_engine,
            image_path=page.image_path,
            text=page.text,
            block_engines=(block.source_engine for block in page.blocks),
        )
        needs_non_ocr_reset = not is_ocr_applicable(content_kind) and (
            page.ocr_confidence is not None
            or page.ocr_calibrated_confidence is not None
            or page.ocr_decision != "not_applicable"
            or page.page_status != "processed"
        )
        if content_kind == (page.ocr_content_kind or "") and not needs_non_ocr_reset:
            continue
        changed += 1
        if content_kind == "native_text":
            native += 1
        elif content_kind == "decorative":
            decorative += 1
        elif content_kind == "photo":
            photo += 1
        if dry_run:
            continue
        page.ocr_content_kind = content_kind
        if not is_ocr_applicable(content_kind):
            page.ocr_confidence = None
            page.ocr_calibrated_confidence = None
            page.ocr_decision = "not_applicable"
            page.ocr_decision_reasons_json = ["content_not_applicable", content_kind]
            page.page_status = "processed"
            for attempt in page.ocr_attempts:
                attempt.selected = False
    if not dry_run:
        db.flush()
    return {
        "pages_scanned": len(pages),
        "pages_changed": changed,
        "native_text": native,
        "decorative": decorative,
        "photo": photo,
    }
