from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import Document, Plan, PlanDimension, PlanRoom


@dataclass(frozen=True)
class ExtractedPlan:
    document_id: int
    project_name: str | None
    scale_text: str | None
    scale_ratio: float | None
    scale_confidence: float | None
    unit: str | None
    has_valid_scale: bool


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
class PlanExtractionResult:
    plan: ExtractedPlan | None
    rooms: list[ExtractedPlanRoom] = field(default_factory=list)
    dimensions: list[ExtractedPlanDimension] = field(default_factory=list)
    needs_review: bool = False


SCALE_RE = re.compile(r"\b(?:escala|e)\s*[:\-]?\s*1\s*[:/]\s*(\d{1,5})\b", re.IGNORECASE)
PROJECT_RE = re.compile(r"\b(?:proyecto|obra)\s*[:\-]\s*(.+)", re.IGNORECASE)
DIMENSION_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(mm|cm|m)\b(?!\s*[2²])", re.IGNORECASE)
ROOM_AREA_RE = re.compile(
    r"\b([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,40}?)\s+(\d+(?:[.,]\d+)?)\s*m\s*(?:2|²)\b",
    re.IGNORECASE,
)
PLAN_KEYWORDS = {"plano", "planta", "escala", "cota", "cotas", "alzado", "seccion", "seccion", "m2"}


def extract_plan(document_id: int, text: str, document_confidence: float | None) -> PlanExtractionResult:
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
    )
    rooms = _extract_rooms(text, base_confidence)
    dimensions = _extract_dimensions(text, base_confidence)
    needs_review = not has_valid_scale or any(room.needs_review for room in rooms)
    if not rooms and not dimensions and not has_valid_scale:
        needs_review = True
    return PlanExtractionResult(plan=plan, rooms=rooms, dimensions=dimensions, needs_review=needs_review)


def persist_plan_extraction(db: Session, document: Document, text: str) -> PlanExtractionResult:
    if document.document_type != "plano" and not _looks_like_plan(text):
        return PlanExtractionResult(plan=None)

    db.execute(delete(Plan).where(Plan.document_id == document.id))
    db.flush()

    result = extract_plan(document.id, text, document.confidence)
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

    return result


def _extract_scale(text: str, document_confidence: float | None) -> tuple[str | None, float | None, float | None]:
    match = SCALE_RE.search(text)
    if not match:
        return None, None, None
    denominator = float(match.group(1))
    if denominator <= 0:
        return None, None, None
    return f"1:{int(denominator)}", denominator, min(0.98, _confidence(document_confidence, fallback=0.84) + 0.08)


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
        for match in ROOM_AREA_RE.finditer(line):
            name = _clean_room_name(match.group(1))
            if not name or _is_non_room_label(name):
                continue
            area = _parse_number(match.group(2))
            if area <= 0:
                continue
            key = (name.lower(), area)
            if key in seen:
                continue
            seen.add(key)
            rooms.append(
                ExtractedPlanRoom(
                    name=name,
                    area_m2=area,
                    width_m=None,
                    length_m=None,
                    polygon_json=None,
                    confidence=confidence,
                    source="ocr_text",
                    needs_review=confidence < 0.70,
                )
            )
    return rooms


def _extract_dimensions(text: str, confidence: float) -> list[ExtractedPlanDimension]:
    dimensions: list[ExtractedPlanDimension] = []
    seen: set[str] = set()
    for match in DIMENSION_RE.finditer(text):
        raw = match.group(0)
        if raw in seen:
            continue
        seen.add(raw)
        value = _parse_number(match.group(1))
        unit = match.group(2).lower()
        value_m = _to_meters(value, unit)
        if value_m <= 0:
            continue
        dimensions.append(
            ExtractedPlanDimension(
                raw_text=raw,
                value=value,
                unit=unit,
                value_m=value_m,
                page_number=None,
                bbox_x1=None,
                bbox_y1=None,
                bbox_x2=None,
                bbox_y2=None,
                confidence=confidence,
            )
        )
    return dimensions


def _looks_like_plan(text: str) -> bool:
    normalized = _normalize(text)
    return any(keyword in normalized for keyword in PLAN_KEYWORDS)


def _to_meters(value: float, unit: str) -> float:
    if unit == "m":
        return value
    if unit == "cm":
        return value / 100
    if unit == "mm":
        return value / 1000
    return 0.0


def _parse_number(value: str) -> float:
    return float(value.replace(".", "").replace(",", ".") if "," in value else value)


def _confidence(value: float | None, *, fallback: float) -> float:
    if value is None:
        return fallback
    return max(0.0, min(1.0, value))


def _clean_room_name(value: str) -> str:
    cleaned = _clean_label(value)
    cleaned = re.sub(r"\b(?:superficie|sup|area)\b\s*[:\-]?\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.title()


def _clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" :-\t")).strip()


def _is_non_room_label(name: str) -> bool:
    normalized = _normalize(name)
    return any(word in normalized for word in ["escala", "cota", "total", "plano", "proyecto", "obra"])


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return normalized.encode("ascii", "ignore").decode("ascii")
