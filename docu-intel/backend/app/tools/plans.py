"""Plan-related tools for the AI agent.

Used to answer questions about architectural plans, rooms, and
dimensions.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, Plan, PlanCadEntity, PlanDimension, PlanRoom
from app.services.search_service import _escape_ilike_wildcards

_CAD_IDENTIFIER_RE = re.compile(r"\b[A-Z]{1,8}\d+(?:\s*-\s*[A-Z]{1,8}\d+)*\b", re.IGNORECASE)


def _cad_identifiers(query: str | None) -> set[str]:
    return {match.upper().replace(" ", "") for match in _CAD_IDENTIFIER_RE.findall(query or "")}


def _cad_entity_search_text(entity: PlanCadEntity) -> str:
    """Return all operator-visible CAD identifiers from an entity."""
    return (
        " ".join(
            (
                entity.entity_handle or "",
                entity.entity_type or "",
                entity.layer or "",
                entity.layout or "",
                json.dumps(entity.geometry_json or {}, ensure_ascii=False),
                json.dumps(entity.properties_json or {}, ensure_ascii=False),
            )
        )
        .upper()
        .replace(" ", "")
    )


def _cad_entity_anchor(entity: PlanCadEntity) -> tuple[float, float] | None:
    geometry = entity.geometry_json or {}
    for key in ("insertion_point", "center", "start"):
        point = geometry.get(key)
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                return float(point[0]), float(point[1])
            except (TypeError, ValueError):
                continue
    return None


def _cad_dimension_anchor(dimension: PlanDimension) -> tuple[float, float] | None:
    coordinates = dimension.coordinates_json or {}
    for key in ("text_point", "definition_points"):
        value = coordinates.get(key)
        point = (
            value[0] if key == "definition_points" and isinstance(value, list) and value else value
        )
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                return float(point[0]), float(point[1])
            except (TypeError, ValueError):
                continue
    return None


def search_plans(db: Session, query: str):
    return list(
        db.scalars(
            select(Plan)
            .where(Plan.project_name.ilike(f"%{_escape_ilike_wildcards(query)}%"))
            .limit(20)
        ).all()
    )


def get_plan_rooms(db: Session, plan_id: int):
    return list(db.scalars(select(PlanRoom).where(PlanRoom.plan_id == plan_id)).all())


def get_plan_dimensions(db: Session, plan_id: int):
    return list(db.scalars(select(PlanDimension).where(PlanDimension.plan_id == plan_id)).all())


def get_room_measurements(db: Session, plan_id: int, room_name: str):
    pattern = f"%{_escape_ilike_wildcards(room_name)}%"
    return list(
        db.scalars(
            select(PlanRoom).where(PlanRoom.plan_id == plan_id).where(PlanRoom.name.ilike(pattern))
        ).all()
    )


def search_plan_room_measurements(db: Session, room_name: str):
    pattern = f"%{_escape_ilike_wildcards(room_name)}%"
    return list(
        db.execute(
            select(Plan, PlanRoom, Document)
            .join(PlanRoom, PlanRoom.plan_id == Plan.id)
            .join(Document, Document.id == Plan.document_id)
            .where(PlanRoom.name.ilike(pattern))
            .where(Document.deleted_at.is_(None))
            .order_by(PlanRoom.needs_review.asc(), Plan.created_at.desc())
            .limit(20)
        ).all()
    )


def get_plan_cad_context(
    db: Session,
    *,
    document_id: int | None = None,
    query: str | None = None,
    limit: int = 8,
):
    """Return bounded native CAD facts for grounding plan questions.

    The result deliberately keeps raw coordinates and provenance alongside
    human-readable dimensions. This lets the answer model distinguish a
    native CAD measurement from OCR text and never invent a conversion.
    """
    stmt = (
        select(Plan, Document)
        .join(Document, Document.id == Plan.document_id)
        .where(Document.deleted_at.is_(None))
        .where(Plan.source_format.in_(["dxf", "dwg"]))
        .order_by(Plan.created_at.desc())
        .limit(limit)
    )
    if document_id is not None:
        stmt = stmt.where(Plan.document_id == document_id)
    if query:
        pattern = f"%{_escape_ilike_wildcards(query)}%"
        stmt = stmt.where(
            Plan.project_name.ilike(pattern) | Document.original_filename.ilike(pattern)
        )
    rows = db.execute(stmt).all()
    # A natural-language question is usually not a filename/project filter
    # (e.g. "qué medidas aparecen en el plano"). If the precise filter has
    # no hit, fall back to the recent accessible plans rather than returning
    # an empty grounding context.
    if not rows and query:
        fallback = (
            select(Plan, Document)
            .join(Document, Document.id == Plan.document_id)
            .where(Document.deleted_at.is_(None))
            .where(Plan.source_format.in_(["dxf", "dwg"]))
            .order_by(Plan.created_at.desc())
            .limit(limit)
        )
        if document_id is not None:
            fallback = fallback.where(Plan.document_id == document_id)
        rows = db.execute(fallback).all()
    result = []
    for plan, document in rows:
        dimensions = list(
            db.scalars(
                select(PlanDimension)
                .where(PlanDimension.plan_id == plan.id)
                .order_by(PlanDimension.id.asc())
            ).all()
        )
        cad_entities = list(
            db.scalars(
                select(PlanCadEntity)
                .where(PlanCadEntity.plan_id == plan.id)
                .order_by(PlanCadEntity.id.asc())
            ).all()
        )
        identifiers = _cad_identifiers(query)
        if identifiers:
            matching_entities = [
                entity
                for entity in cad_entities
                if any(identifier in _cad_entity_search_text(entity) for identifier in identifiers)
            ]
            non_matching_entities = [
                entity for entity in cad_entities if entity not in matching_entities
            ]
            cad_entities = matching_entities + non_matching_entities

            anchors = tuple(
                anchor for entity in matching_entities if (anchor := _cad_entity_anchor(entity))
            )
            if anchors:

                def dimension_distance(
                    dimension: PlanDimension,
                    *,
                    anchors: tuple[tuple[float, float], ...] = anchors,
                ) -> float:
                    anchor = _cad_dimension_anchor(dimension)
                    if anchor is None:
                        return float("inf")
                    return min(
                        (anchor[0] - entity_anchor[0]) ** 2 + (anchor[1] - entity_anchor[1]) ** 2
                        for entity_anchor in anchors
                    )

                dimensions.sort(key=dimension_distance)
        result.append(
            {
                "plan": plan,
                "document": document,
                "dimensions": dimensions,
                "cad_entities": cad_entities,
            }
        )
    return result
