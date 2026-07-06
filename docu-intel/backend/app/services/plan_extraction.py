from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Document,
    DocumentBlock,
    DocumentPage,
    Plan,
    PlanDimension,
    PlanRoom,
    PlanSymbol,
)

logger = logging.getLogger("app.services.plan_extraction")


@dataclass(frozen=True)
class ExtractedPlan:
    document_id: int
    project_name: str | None
    scale_text: str | None
    scale_ratio: float | None
    scale_confidence: float | None
    unit: str | None
    has_valid_scale: bool
    # PL1: pixels-per-inch of the rasterized page where the plan lives.
    # Used to convert the bbox of each dimension caption into millimetres
    # and validate it against the OCR-derived value_m.
    dpi: float | None = None


@dataclass(frozen=True)
class ExtractedPlanRoom:
    name: str
    area_m2: float | None
    width_m: float | None
    length_m: float | None
    polygon_json: dict | None
    confidence: float
    source: str
    needs_review: bool


@dataclass(frozen=True)
class ExtractedPlanDimension:
    raw_text: str
    value: float
    unit: str
    value_m: float
    page_number: int | None
    bbox_x1: float | None
    bbox_y1: float | None
    bbox_x2: float | None
    bbox_y2: float | None
    confidence: float


@dataclass(frozen=True)
class PlanTextBlock:
    text: str
    page_number: int | None = None
    bbox: tuple[float | None, float | None, float | None, float | None] | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class PlanExtractionResult:
    plan: ExtractedPlan | None
    rooms: list[ExtractedPlanRoom] = field(default_factory=list)
    dimensions: list[ExtractedPlanDimension] = field(default_factory=list)
    needs_review: bool = False


SCALE_RE = re.compile(r"\b(?:escala|e)\s*[:\-]?\s*1\s*[:/]\s*(\d{1,5})\b", re.IGNORECASE)
PROJECT_RE = re.compile(r"\b(?:proyecto|obra)\s*[:\-]\s*(.+)", re.IGNORECASE)
NUMBER_PATTERN = r"(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
DIMENSION_RE = re.compile(rf"\b({NUMBER_PATTERN})\s*(mm|cm|m)\b(?!\s*[2²])", re.IGNORECASE)
ROOM_AREA_RE = re.compile(
    rf"^\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 ._/\-]{{1,60}}?)\s+({NUMBER_PATTERN})\s*m\s*(?:2|²)\b",
    re.IGNORECASE,
)
ROOM_DIMENSION_PAIR_RE = re.compile(
    rf"^\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 ._/\-]{{1,60}}?)\s+({NUMBER_PATTERN})\s*[x×X]\s*({NUMBER_PATTERN})\s*m\b",
    re.IGNORECASE,
)
ROOM_AREA_ALT_RE = re.compile(
    rf"({NUMBER_PATTERN})\s*m\s*(?:2|²)\b.*?([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 ._]{{1,40}})",
    re.IGNORECASE,
)
PLAN_KEYWORDS = {"plano", "planta", "escala", "cota", "cotas", "alzado", "seccion", "m2"}
NON_ROOM_WORDS = {
    "escala",
    "cota",
    "cotas",
    "total",
    "plano",
    "proyecto",
    "obra",
    "planta",
    "plantas",
    "nivel",
    "seccion",
    "alzado",
    "corte",
    "detalle",
    "referencia",
    "leyenda",
    "simbologia",
    "notas",
}


def extract_plan(
    document_id: int,
    text: str,
    document_confidence: float | None,
    *,
    text_blocks: Sequence[PlanTextBlock] | None = None,
    dpi: float | None = None,
) -> PlanExtractionResult:
    if not _looks_like_plan(text):
        return PlanExtractionResult(plan=None)

    scale_text, scale_ratio, scale_confidence = _extract_scale(text, document_confidence)
    project_name = _extract_project_name(text)
    has_valid_scale = bool(scale_ratio and scale_ratio > 0)
    base_confidence = _confidence(document_confidence, fallback=0.78)
    plan = ExtractedPlan(
        document_id=document_id,
        project_name=project_name,
        scale_text=scale_text,
        scale_ratio=scale_ratio,
        scale_confidence=scale_confidence,
        unit="m",
        has_valid_scale=has_valid_scale,
        dpi=dpi,
    )
    rooms = _extract_rooms(text, base_confidence)
    dimensions = _extract_dimensions(text, base_confidence, text_blocks=text_blocks)
    needs_review = not has_valid_scale or any(room.needs_review for room in rooms)
    if not rooms and not dimensions and not has_valid_scale:
        needs_review = True
    result = PlanExtractionResult(
        plan=plan, rooms=rooms, dimensions=dimensions, needs_review=needs_review
    )
    # PL1: cross-check the OCR-derived value_m of every dimension
    # against the bbox of its caption, using the page DPI and the
    # declared scale_ratio. Mismatches lower the confidence and force
    # the dimension to be reviewed. We do this here (not in
    # ``persist_plan_extraction``) so unit tests of ``extract_plan``
    # get the same behaviour as the production persistence path.
    if plan.has_valid_scale and dpi:
        result = _validate_dimensions_against_scale(result, dpi)
    return result


def persist_plan_extraction(db: Session, document: Document, text: str) -> PlanExtractionResult:
    if document.document_type != "plano" and not _looks_like_plan(text):
        return PlanExtractionResult(plan=None)

    db.execute(delete(Plan).where(Plan.document_id == document.id))
    db.flush()

    dpi = _load_plan_page_dpi(db, document.id)
    result = extract_plan(
        document.id,
        text,
        document.confidence,
        text_blocks=_load_plan_text_blocks(db, document.id),
        dpi=dpi,
    )
    if not result.plan:
        return result

    plan = Plan(
        document_id=document.id,
        project_name=result.plan.project_name,
        scale_text=result.plan.scale_text,
        scale_ratio=result.plan.scale_ratio,
        scale_confidence=result.plan.scale_confidence,
        unit=result.plan.unit,
        has_valid_scale=result.plan.has_valid_scale,
    )
    db.add(plan)
    db.flush()

    for room in result.rooms:
        db.add(
            PlanRoom(
                plan_id=plan.id,
                name=room.name,
                area_m2=room.area_m2,
                width_m=room.width_m,
                length_m=room.length_m,
                polygon_json=room.polygon_json,
                confidence=room.confidence,
                source=room.source,
                needs_review=room.needs_review,
            )
        )

    for dimension in result.dimensions:
        db.add(
            PlanDimension(
                plan_id=plan.id,
                raw_text=dimension.raw_text,
                value=dimension.value,
                unit=dimension.unit,
                value_m=dimension.value_m,
                page_number=dimension.page_number,
                bbox_x1=dimension.bbox_x1,
                bbox_y1=dimension.bbox_y1,
                bbox_x2=dimension.bbox_x2,
                bbox_y2=dimension.bbox_y2,
                confidence=dimension.confidence,
            )
        )

    # P2 — YOLO symbol detection. Runs after dimensions are persisted
    # so the symbol rows do not block the cheaper text-based extraction
    # if YOLO is slow or unavailable. The detector is fail-safe
    # (returns an empty list when the model is missing or errors), so
    # this call never breaks the rest of the pipeline.
    _persist_plan_symbols(db, plan, document.id)

    return result


def _persist_plan_symbols(db: Session, plan: Plan, document_id: int) -> int:
    """Run YOLO symbol detection on every page of the plan and persist
    the results as :class:`PlanSymbol` rows.

    Returns the number of symbols persisted. Any error (missing
    model, missing page image, OOM) is swallowed so the plan
    processing pipeline stays robust. The caller has already
    flushed the ``Plan`` row, so ``plan.id`` is available.
    """
    # Lazy import: YOLO is an optional heavy dependency and we don't
    # want to force its import on every test / CLI invocation.
    try:
        from app.services.plan_symbols import (
            detect_symbols,
            is_model_available,
        )
    except Exception:  # pragma: no cover - defensive
        return 0

    # Cheap early-out: if the model never loaded (e.g. ultralytics
    # not installed, or the model file is missing), skip without
    # touching the database.
    try:
        if not is_model_available():
            # Try one more time: ``is_model_available`` only returns
            # True after the lazy load has completed. Trigger it by
            # calling ``detect_symbols`` on a non-existent path —
            # this warms the cache, then bails out because the file
            # is missing.
            detect_symbols("/nonexistent.png")
            if not is_model_available():
                return 0
    except Exception:  # pragma: no cover - defensive
        return 0

    pages = db.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number.asc().nullslast())
    ).all()

    total = 0
    source_model = _current_source_model()
    for page in pages:
        image_path = page.image_path
        if not image_path:
            continue
        # ``image_path`` is a string stored as either a forward-slash
        # relative path or a Windows path. The detector opens it
        # via ``Path(image_path)``; containerised workers need the
        # absolute path. We try the literal value first, then fall
        # back to joining with ``settings.files_dir``.
        from pathlib import Path

        from app.core.config import settings

        candidate = Path(image_path)
        if not candidate.exists():
            try:
                candidate = Path(settings.files_dir) / image_path.lstrip("/\\")
            except Exception:
                continue
        if not candidate.exists():
            continue

        page_number = page.page_number or 1
        try:
            detections = detect_symbols(
                candidate,
                page_number=page_number,
            )
        except Exception:  # pragma: no cover - defensive
            continue

        for sym in detections:
            x1, y1, x2, y2 = sym.bbox
            db.add(
                PlanSymbol(
                    plan_id=plan.id,
                    symbol_class=sym.symbol_class,
                    confidence=sym.confidence,
                    page_number=page_number,
                    bbox_x1=float(x1),
                    bbox_y1=float(y1),
                    bbox_x2=float(x2),
                    bbox_y2=float(y2),
                    source_model=source_model,
                )
            )
            total += 1
    return total


def _current_source_model() -> str:
    """Return a short label identifying the model currently configured.

    Used to fill the ``source_model`` column on every persisted symbol
    row. When the operator swaps the model, future rows carry the
    new label, which makes it easy to spot stale rows in the DB
    (e.g. ``SELECT COUNT(*) FROM plan_symbols WHERE source_model !=
    current_label``).
    """
    try:
        from app.core.config import settings

        return settings.plan_symbols_model_path
    except Exception:  # pragma: no cover - defensive
        return "unknown"


def _load_plan_text_blocks(db: Session, document_id: int) -> list[PlanTextBlock]:
    blocks = db.scalars(
        select(DocumentBlock)
        .where(DocumentBlock.document_id == document_id)
        .where(DocumentBlock.text.is_not(None))
        .order_by(DocumentBlock.page_number.asc().nullslast(), DocumentBlock.id.asc())
    ).all()
    return [
        PlanTextBlock(
            text=block.text or "",
            page_number=block.page_number,
            bbox=(block.bbox_x1, block.bbox_y1, block.bbox_x2, block.bbox_y2),
            confidence=block.confidence,
        )
        for block in blocks
        if block.text
    ]


def _extract_scale(
    text: str, document_confidence: float | None
) -> tuple[str | None, float | None, float | None]:
    match = SCALE_RE.search(text)
    if not match:
        return None, None, None
    denominator = float(match.group(1))
    if denominator <= 0:
        return None, None, None
    return (
        f"1:{int(denominator)}",
        denominator,
        min(0.98, _confidence(document_confidence, fallback=0.84) + 0.08),
    )


def _extract_project_name(text: str) -> str | None:
    for line in text.splitlines():
        match = PROJECT_RE.search(line.strip())
        if match:
            return _clean_label(match.group(1))[:255] or None
    return None


def _extract_rooms(text: str, confidence: float) -> list[ExtractedPlanRoom]:
    rooms: list[ExtractedPlanRoom] = []
    seen: set[tuple[str, float]] = set()
    for line in text.splitlines():
        stripped = line.strip()
        area_match = ROOM_AREA_RE.search(stripped)
        if area_match:
            name = _clean_room_name(area_match.group(1))
            area = _parse_number(area_match.group(2), has_unit=True)
            _append_room(
                rooms,
                seen,
                name=name,
                area_m2=area,
                width_m=None,
                length_m=None,
                confidence=confidence,
            )
            continue

        pair_match = ROOM_DIMENSION_PAIR_RE.search(stripped)
        if pair_match:
            name = _clean_room_name(pair_match.group(1))
            width = _parse_number(pair_match.group(2), has_unit=True)
            length = _parse_number(pair_match.group(3), has_unit=True)
            area = round(width * length, 4) if width > 0 and length > 0 else None
            _append_room(
                rooms,
                seen,
                name=name,
                area_m2=area,
                width_m=width,
                length_m=length,
                confidence=confidence,
            )
            continue

        # Alt pattern: "20 m2 Dormitorio 1" (area before name)
        alt_match = ROOM_AREA_ALT_RE.search(stripped)
        if alt_match:
            area = _parse_number(alt_match.group(1), has_unit=True)
            name = _clean_room_name(alt_match.group(2))
            _append_room(
                rooms,
                seen,
                name=name,
                area_m2=area,
                width_m=None,
                length_m=None,
                confidence=confidence * 0.9,
            )
    return rooms


def _extract_dimensions(
    text: str,
    confidence: float,
    *,
    text_blocks: Sequence[PlanTextBlock] | None = None,
) -> list[ExtractedPlanDimension]:
    dimensions: list[ExtractedPlanDimension] = []
    seen: set[
        tuple[str, int | None, tuple[float | None, float | None, float | None, float | None] | None]
    ] = set()

    sources = list(text_blocks or [])
    if not sources:
        sources = [PlanTextBlock(text=text, confidence=confidence)]

    for source in sources:
        for match in DIMENSION_RE.finditer(source.text):
            _append_dimension_from_match(dimensions, seen, match, source, confidence)

    return dimensions


def _append_dimension_from_match(
    dimensions: list[ExtractedPlanDimension],
    seen: set[
        tuple[str, int | None, tuple[float | None, float | None, float | None, float | None] | None]
    ],
    match: re.Match[str],
    source: PlanTextBlock,
    fallback_confidence: float,
) -> None:
    raw = match.group(0)
    bbox = source.bbox
    key = (raw, source.page_number, bbox)
    if key in seen:
        return
    seen.add(key)
    value = _parse_number(match.group(1), has_unit=True)
    unit = match.group(2).lower()
    value_m = _to_meters(value, unit)
    if value_m <= 0:
        return
    x1, y1, x2, y2 = bbox or (None, None, None, None)
    dimensions.append(
        ExtractedPlanDimension(
            raw_text=raw,
            value=value,
            unit=unit,
            value_m=value_m,
            page_number=source.page_number,
            bbox_x1=x1,
            bbox_y1=y1,
            bbox_x2=x2,
            bbox_y2=y2,
            confidence=_confidence(source.confidence, fallback=fallback_confidence),
        )
    )


def _looks_like_plan(text: str) -> bool:
    normalized = _normalize(text)
    signals: set[str] = set()
    for keyword in PLAN_KEYWORDS:
        if keyword == "m2":
            if re.search(r"\bm\s*2\b", normalized):
                signals.add(keyword)
            continue
        if re.search(rf"\b{re.escape(keyword)}\b", normalized):
            signals.add(keyword)
    return len(signals) >= 2


def _to_meters(value: float, unit: str) -> float:
    if unit == "m":
        return value
    if unit == "cm":
        return value / 100
    if unit == "mm":
        return value / 1000
    return 0.0


def _parse_number(value: str, *, has_unit: bool = False) -> float:
    """Parse a numeric string, handling ES/EN conventions.

    When ``has_unit`` is True (the number is adjacent to a unit like m,
    cm, mm), a dot with 3 digits after it is treated as a decimal
    separator (e.g. ``1.234 m`` → 1.234), not as a thousands separator.
    This matches the dominant convention in architectural plans.

    Without a unit, ``1.234`` is treated as 1234 (ES thousands convention)
    to stay consistent with ``_parse_amount`` in business_extraction.
    """
    cleaned = re.sub(r"\s+", "", value.strip())
    if not cleaned:
        return 0.0

    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", cleaned):
        if has_unit:
            # "1.234" with unit → 1.234 (decimal in plans)
            # But "1.234.567" → still thousands
            parts = cleaned.replace(",", ".").split(".")
            if len(parts) == 2:
                return float(cleaned.replace(",", "."))
            return float(cleaned.replace(".", "").replace(",", "."))
        return float(cleaned.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", cleaned):
        return float(cleaned.replace(",", ""))
    if re.fullmatch(r"\d+,\d+", cleaned):
        integer, fraction = cleaned.split(",", 1)
        if len(fraction) == 3 and len(integer) <= 3:
            return float(integer + fraction)
        return float(f"{integer}.{fraction}")
    if re.fullmatch(r"\d+\.\d+", cleaned):
        integer, fraction = cleaned.split(".", 1)
        if len(fraction) == 3 and len(integer) <= 3:
            if has_unit:
                # "1.234" with unit → 1.234 (decimal)
                return float(cleaned)
            return float(integer + fraction)
        return float(cleaned)
    return float(cleaned.replace(",", "."))


def _confidence(value: float | None, *, fallback: float) -> float:
    if value is None:
        return fallback
    return max(0.0, min(1.0, value))


def _clean_room_name(value: str) -> str:
    cleaned = _clean_label(value)
    cleaned = re.sub(r"\b(?:superficie|sup|area)\b\s*[:\-]?\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned


def _clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" :-\t")).strip()


def _is_non_room_label(name: str) -> bool:
    normalized = _normalize(name)
    words = set(re.findall(r"[a-z0-9]+", normalized))
    return bool(words & NON_ROOM_WORDS)


def _append_room(
    rooms: list[ExtractedPlanRoom],
    seen: set[tuple[str, float]],
    *,
    name: str,
    area_m2: float | None,
    width_m: float | None,
    length_m: float | None,
    confidence: float,
) -> None:
    if not name or _is_non_room_label(name):
        return
    if area_m2 is not None and area_m2 <= 0:
        return
    if width_m is not None and width_m <= 0:
        return
    if length_m is not None and length_m <= 0:
        return
    dedupe_area = area_m2 if area_m2 is not None else 0.0
    key = (name.lower(), dedupe_area)
    if key in seen:
        return
    seen.add(key)
    rooms.append(
        ExtractedPlanRoom(
            name=name,
            area_m2=area_m2,
            width_m=width_m,
            length_m=length_m,
            polygon_json=None,
            confidence=confidence,
            source="ocr_text",
            # Centralised OCR-confidence threshold (see
            # settings.low_ocr_confidence_threshold — default 0.60).
            needs_review=confidence < 0.60,
        )
    )


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return normalized.encode("ascii", "ignore").decode("ascii")


# ---------------------------------------------------------------------------
# PL1 — usar la escala para validar / derivar dimensiones
# ---------------------------------------------------------------------------
#
# The ``PlanDimension`` rows we extract from OCR carry a bbox of the
# caption text (e.g. "3,50") plus the value we read from that text
# (e.g. ``3.50 m``). The declared ``Plan.scale_ratio`` is a global
# "1:N" claim, e.g. "1:100". When we also know the DPI of the page
# where the caption lives, we can:
#
#   1. compute the on-paper length in mm of the caption bbox;
#   2. convert that to the real-world length in mm by multiplying by
#      the scale ratio;
#   3. compare with the value_m that the OCR read.
#
# A dimension that disagrees with its own bbox is almost always a sign
# that the OCR mis-read the number ("3,50" read as "8,50" on a
# rotated scan, for example). We mark those for review instead of
# silently propagating the bad number.
#
# Note: we compare the *longer* side of the caption bbox to the
# declared value. A "3,50" caption rendered at 12pt is roughly 25 px
# wide on a 300 dpi page, so a 35 m caption (one pixel of the wall it
# annotates) would not validate against a 3.50 m value. This is the
# expected behaviour: PL1 only validates, it does not invent new
# measurements.

# Tolerancia del 30 % entre el valor OCR y el valor derivado del bbox.
# Lo bastante generosa para tolerar tipografías y antialiasing; lo
# bastante estricta para cazar OCR claramente erróneo.
_DIMENSION_BBOX_TOLERANCE = 0.30
# Altura mínima del bbox en píxeles para que la validación sea
# significativa (un bbox degenerado de 1 px se ignora).
_MIN_BBOX_SIDE_PX = 4.0


def _load_plan_page_dpi(db: Session, document_id: int) -> float | None:
    """Best-effort effective DPI of the page where the plan was
    rasterized.

    We don't store the original PDF's render DPI on the model, but
    ``settings.pdf_ocr_dpi`` is the DPI we use everywhere in the
    pipeline. If a page has stored ``width`` and ``height`` and we
    know its real-world size, we could derive the actual DPI; we don't
    have the latter, so we just return the configured value. The
    caller is expected to treat this as a soft signal and not as
    ground truth.
    """
    from app.core.config import settings

    # TODO: derive real DPI from page metadata if available
    return float(settings.pdf_ocr_dpi)


def _bbox_dimensions_m(
    bbox: tuple[float | None, float | None, float | None, float | None] | None,
    *,
    dpi: float,
) -> float | None:
    """Return the longer side of the bbox in metres, given the page
    DPI. Returns ``None`` if the bbox is missing, has ``None``
    components, or is too small to be meaningful.
    """
    if not bbox or dpi <= 0:
        return None
    x1, y1, x2, y2 = bbox
    if None in (x1, y1, x2, y2):
        return None
    width_px = abs(float(x2) - float(x1))
    height_px = abs(float(y2) - float(y1))
    long_side_px = max(width_px, height_px)
    if long_side_px < _MIN_BBOX_SIDE_PX:
        return None
    # 1 inch = 25.4 mm. dpi is pixels per inch. So 1 px = 25.4 / dpi mm.
    mm_per_px = 25.4 / dpi
    long_side_m = (long_side_px * mm_per_px) / 1000.0
    return long_side_m


def _expected_dimension_m_from_bbox(
    bbox: tuple[float | None, float | None, float | None, float | None] | None,
    *,
    scale_ratio: float,
    dpi: float,
) -> float | None:
    """Apply the scale to a bbox-derived on-paper length to get a
    real-world length in metres.

    Scale ``1:100`` means 1 unit on the drawing equals 100 real
    units, so the on-paper mm becomes ``mm * scale_ratio`` real mm.
    """
    on_paper_m = _bbox_dimensions_m(bbox, dpi=dpi)
    if on_paper_m is None or scale_ratio <= 0:
        return None
    return on_paper_m * scale_ratio


def _validate_dimensions_against_scale(
    result: PlanExtractionResult,
    dpi: float,
) -> PlanExtractionResult:
    """Cross-check each dimension's OCR value against the bbox /
    scale / dpi triple and lower its confidence if they disagree.

    The function never raises and never mutates the OCR text or the
    declared value: a dimension that disagrees is *flagged* for
    review by halving its confidence and adding it to
    ``needs_review``. This matches the project rule "if the source
    is uncertain, mark it for review, do not invent a corrected
    value".
    """
    if not result.plan or not result.dimensions:
        return result
    scale_ratio = result.plan.scale_ratio
    if not scale_ratio or scale_ratio <= 0:
        return result

    validated: list[ExtractedPlanDimension] = []
    needs_review = result.needs_review
    for dimension in result.dimensions:
        bbox = (
            dimension.bbox_x1,
            dimension.bbox_y1,
            dimension.bbox_x2,
            dimension.bbox_y2,
        )
        expected_m = _expected_dimension_m_from_bbox(bbox, scale_ratio=scale_ratio, dpi=dpi)
        # Without a comparable measurement we cannot validate; keep
        # the OCR value as-is.
        if expected_m is None or dimension.value_m <= 0:
            if expected_m is None:
                logger.debug("No se puede validar cota: bbox ausente")
            validated.append(dimension)
            continue
        # The OCR may have read the value in cm / mm; ``value_m`` is
        # already converted to metres upstream. Compare in metres.
        relative_error = abs(expected_m - dimension.value_m) / dimension.value_m
        if relative_error > _DIMENSION_BBOX_TOLERANCE:
            logger.info(
                "PL1: dimension disagrees with bbox (document_id=%s page=%s value=%s expected=%s rel_err=%.2f)",
                result.plan.document_id,
                dimension.page_number,
                dimension.value_m,
                expected_m,
                relative_error,
            )
            validated.append(
                ExtractedPlanDimension(
                    raw_text=dimension.raw_text,
                    value=dimension.value,
                    unit=dimension.unit,
                    value_m=dimension.value_m,
                    page_number=dimension.page_number,
                    bbox_x1=dimension.bbox_x1,
                    bbox_y1=dimension.bbox_y1,
                    bbox_x2=dimension.bbox_x2,
                    bbox_y2=dimension.bbox_y2,
                    confidence=round(dimension.confidence * 0.5, 4),
                )
            )
            needs_review = True
        else:
            validated.append(dimension)

    return PlanExtractionResult(
        plan=result.plan,
        rooms=result.rooms,
        dimensions=validated,
        needs_review=needs_review,
    )


# ---------------------------------------------------------------------------
# P5 — Multi-sheet plan phase detection
# ---------------------------------------------------------------------------

# Patterns for building phases. The regex matches the most common
# Spanish / English plan-header conventions. The match is
# case-insensitive and normalised to a canonical form.
_PHASE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bplanta\s+ba(?:ja|ixa)\b", re.IGNORECASE), "PLANTA BAJA"),
    (re.compile(r"\bplanta\s+primera\b", re.IGNORECASE), "PLANTA PRIMERA"),
    (re.compile(r"\bplanta\s+segunda\b", re.IGNORECASE), "PLANTA SEGUNDA"),
    (re.compile(r"\bplanta\s+tercera\b", re.IGNORECASE), "PLANTA TERCERA"),
    (re.compile(r"\bplanta\s+(\d+)[ªº]?\b", re.IGNORECASE), None),  # dynamic
    (re.compile(r"\bplanta\s+(\d+)\b", re.IGNORECASE), None),  # "Planta 3"
    (re.compile(r"\bcubierta\b", re.IGNORECASE), "CUBIERTA"),
    (re.compile(r"\bs[oó]tano\b", re.IGNORECASE), "SÓTANO"),
    (re.compile(r"\bsemi[-\s]?s[oó]tano\b", re.IGNORECASE), "SEMI-SÓTANO"),
    (
        re.compile(
            r"\balzado\s+(norte|sur|este|oeste|principal|posterior|lateral)\b", re.IGNORECASE
        ),
        None,
    ),
    (re.compile(r"\bsecci[oó]n\s+([A-Z])\s*[-–]?\s*([A-Z])?\b", re.IGNORECASE), None),
    (re.compile(r"\bsecci[oó]n\s+([A-Z])\b", re.IGNORECASE), None),
    (re.compile(r"\bdetalle\s+(.+?)\s*$", re.IGNORECASE), None),
]

_REVISION_RE = re.compile(
    r"\b(?:rev(?:isi[oó]n)?|rev)\s*[:.\-]?\s*([A-Z0-9]{1,5})\b",
    re.IGNORECASE,
)


def extract_plan_phase(text: str) -> tuple[str | None, str | None]:
    """Detect the building phase and revision from the plan text.

    Returns ``(project_phase, revision)``. ``project_phase`` is
    a canonical label (e.g. ``"PLANTA PRIMERA"``, ``"ALZADO
    NORTE"``, ``"SECCIÓN A-A"``) or ``None`` when no phase is
    detected. ``revision`` is the revision letter/number (e.g.
    ``"A"``, ``"01"``, ``"REV02"``) or ``None``.

    The function is case-insensitive and normalises whitespace.
    Multiple matches are resolved by *first match wins* (the
    patterns are ordered from most specific to least specific).
    """
    if not text:
        return None, None

    # Phase detection.
    phase: str | None = None
    for pattern, canonical in _PHASE_PATTERNS:
        match = pattern.search(text)
        if match:
            if canonical is not None:
                phase = canonical
            else:
                # Dynamic match: build the label from the capture
                # groups.
                groups = [g for g in match.groups() if g is not None]
                if groups:
                    phase = f"{match.group(0).strip().upper()}"
                else:
                    phase = match.group(0).strip().upper()
            break

    # Revision detection.
    revision: str | None = None
    rev_match = _REVISION_RE.search(text)
    if rev_match:
        revision = rev_match.group(1).upper()

    return phase, revision
