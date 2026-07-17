"""Technical-document orchestration with durable, idempotent facts.

The document pipeline invokes this module after the deterministic plan and
business extractors.  It deliberately reuses their persisted output instead
of maintaining a second set of approximate counters.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

logger = logging.getLogger("app.services.technical_pipeline")


@dataclass
class PipelineResult:
    """Auditable summary of one technical-document extraction."""

    document_id: int
    document_type: str
    plan_id: int | None = None
    rooms_extracted: int = 0
    dimensions_extracted: int = 0
    symbols_extracted: int = 0
    geometry_lines: int = 0
    geometry_polylines: int = 0
    geometry_arcs: int = 0
    chapters_extracted: int = 0
    specs_extracted: int = 0
    work_chapters_extracted: int = 0
    work_items_extracted: int = 0
    total_budget: float = 0.0
    validation_score: float = 0.0
    contradictions: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    _plan_validation_payload: dict[str, Any] = field(default_factory=dict, repr=False)
    _memory_sections: list[Any] = field(default_factory=list, repr=False)
    _memory_specs: list[Any] = field(default_factory=list, repr=False)


def process_technical_document(
    db: Session | None,
    document_id: int,
    text: str,
    filename: str,
    document_type: str,
    blocks: list[Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> PipelineResult:
    """Extract and persist facts for a technical document.

    The ``db=None`` mode is intentionally supported for fixture/CLI validation
    and produces the same deterministic counters, without writes.
    """
    result = PipelineResult(document_id=document_id, document_type=document_type)
    if not document_type or document_type == "unknown":
        from app.services.classification import classify_document

        classification = classify_document(filename=filename, source_path=None, text=text)
        document_type = classification.document_type
        result.document_type = document_type

    is_plan = document_type.startswith("plano") or document_type == "plano"
    is_memory = "memoria" in document_type
    # The classifier emits ``medicion`` for the documents already in the
    # corpus, while older imports use ``mediciones_obra``.  Both describe the
    # same structured work-item workflow and must reach the durable extractor.
    is_budget = document_type in {"medicion", "mediciones_obra", "presupuesto"}

    if is_plan:
        _process_plan_data(result, text, blocks, db=db)
    elif is_memory:
        _process_memory_data(result, text, document_id)
    elif is_budget:
        _process_budget_data(result, text, document_id, db=db)

    if manifest:
        _validate_result(result, manifest, is_plan=is_plan, is_memory=is_memory)
    return result


def _process_plan_data(
    result: PipelineResult,
    text: str,
    blocks: list[Any] | None,
    *,
    db: Session | None,
) -> None:
    """Read persisted plan facts, or run the plan extractor in pure mode."""
    if db is not None:
        from app.models import Plan, PlanDimension, PlanRoom, PlanSymbol

        plan = db.scalar(select(Plan).where(Plan.document_id == result.document_id))
        if plan is not None:
            rooms = list(db.scalars(select(PlanRoom).where(PlanRoom.plan_id == plan.id)).all())
            dimensions = list(
                db.scalars(select(PlanDimension).where(PlanDimension.plan_id == plan.id)).all()
            )
            symbols = list(
                db.scalars(select(PlanSymbol).where(PlanSymbol.plan_id == plan.id)).all()
            )
            result.plan_id = plan.id
            result.rooms_extracted = len(rooms)
            result.dimensions_extracted = len(dimensions)
            result.symbols_extracted = len(symbols)
            symbol_counts: dict[str, int] = {}
            for symbol in symbols:
                symbol_counts[symbol.symbol_class] = symbol_counts.get(symbol.symbol_class, 0) + 1
            result._plan_validation_payload = {
                "document_type": result.document_type,
                "scale": plan.scale_text or "",
                "phase": plan.project_phase or "",
                "revision": plan.revision or "",
                "rooms": [{"name": room.name or "", "area_m2": room.area_m2} for room in rooms],
                "dimensions": [
                    {"label": dimension.raw_text or "", "value_m": dimension.value_m}
                    for dimension in dimensions
                ],
                "symbols": symbol_counts,
            }
            _set_geometry_summary(result, text)
            return

    from app.services.plan_extraction import PlanTextBlock, extract_plan, extract_plan_phase

    text_blocks: list[PlanTextBlock] = []
    for block in blocks or []:
        block_text = getattr(block, "text", None)
        if not block_text:
            continue
        bbox = getattr(block, "bbox", None)
        if bbox is None and all(
            hasattr(block, attr) for attr in ("bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2")
        ):
            coordinates = (block.bbox_x1, block.bbox_y1, block.bbox_x2, block.bbox_y2)
            bbox = coordinates if all(value is not None for value in coordinates) else None
        text_blocks.append(
            PlanTextBlock(
                text=block_text,
                page_number=getattr(block, "page_number", None),
                bbox=bbox,
                confidence=getattr(block, "confidence", None),
            )
        )
    extracted = extract_plan(
        result.document_id,
        text,
        document_confidence=None,
        text_blocks=text_blocks,
    )
    if extracted.plan is not None:
        phase, revision = extract_plan_phase(text)
        result.rooms_extracted = len(extracted.rooms)
        result.dimensions_extracted = len(extracted.dimensions)
        result._plan_validation_payload = {
            "document_type": result.document_type,
            "scale": extracted.plan.scale_text or "",
            "phase": phase or "",
            "revision": revision or "",
            "rooms": [{"name": room.name, "area_m2": room.area_m2} for room in extracted.rooms],
            "dimensions": [
                {"label": dimension.raw_text, "value_m": dimension.value_m}
                for dimension in extracted.dimensions
            ],
            "symbols": {},
        }
    _set_geometry_summary(result, text)


def _set_geometry_summary(result: PipelineResult, text: str) -> None:
    """Record DXF geometry diagnostics without fabricating domain facts."""
    geometry = re.search(r"Geometr(?:ía|ia):\s*(.+)", text, flags=re.IGNORECASE)
    if geometry is None:
        return
    payload = geometry.group(1)
    for pattern, attribute in (
        (r"line=(\d+)", "geometry_lines"),
        (r"polyline=(\d+)", "geometry_polylines"),
        (r"arc=(\d+)", "geometry_arcs"),
    ):
        match = re.search(pattern, payload, flags=re.IGNORECASE)
        if match:
            setattr(result, attribute, int(match.group(1)))


def _process_memory_data(result: PipelineResult, text: str, document_id: int) -> None:
    from app.services.memory_extraction import extract_specifications, parse_memory_structure
    from app.services.validation import detect_contradictions

    sections = parse_memory_structure(text, document_type=result.document_type)
    specs = extract_specifications(text, document_id=document_id)
    result.chapters_extracted = _count_sections(sections)
    result.specs_extracted = len(specs)
    result.contradictions = len(detect_contradictions(memory_specs=specs))
    result._memory_sections = sections
    result._memory_specs = specs


def _process_budget_data(
    result: PipelineResult,
    text: str,
    document_id: int,
    *,
    db: Session | None,
) -> None:
    from app.services.work_item_extraction import aggregate_work_items, extract_work_items_from_text

    chapters, items, breakdowns = extract_work_items_from_text(text, document_id=document_id)
    result.work_chapters_extracted = len(chapters)
    result.work_items_extracted = len(items)
    result.total_budget = float(aggregate_work_items(items).get("total_price", 0))
    if db is not None:
        _persist_work_items(db, document_id, chapters, items, breakdowns)


def _persist_work_items(
    db: Session,
    document_id: int,
    chapters: list[Any],
    items: list[Any],
    breakdowns: list[Any],
) -> None:
    """Replace construction facts for one document, preserving idempotence."""
    from app.models import ConstructionWorkItem, WorkChapter, WorkItemBreakdown
    from app.models.project import DocumentOccurrence

    existing_item_ids = list(
        db.scalars(
            select(ConstructionWorkItem.id).where(ConstructionWorkItem.document_id == document_id)
        ).all()
    )
    if existing_item_ids:
        db.execute(
            delete(WorkItemBreakdown).where(WorkItemBreakdown.work_item_id.in_(existing_item_ids))
        )
    db.execute(delete(ConstructionWorkItem).where(ConstructionWorkItem.document_id == document_id))
    db.execute(delete(WorkChapter).where(WorkChapter.document_id == document_id))
    project_id = db.scalar(
        select(DocumentOccurrence.project_id)
        .where(DocumentOccurrence.document_id == document_id)
        .where(DocumentOccurrence.project_id.is_not(None))
        .order_by(DocumentOccurrence.id)
        .limit(1)
    )

    chapter_by_code: dict[str, Any] = {}
    for extracted in chapters:
        chapter = WorkChapter(
            project_id=project_id,
            code=extracted.code,
            title=extracted.title,
            order_index=extracted.order_index,
            document_id=document_id,
        )
        db.add(chapter)
        chapter_by_code[extracted.code] = chapter
    db.flush()
    for extracted in chapters:
        parent = chapter_by_code.get(extracted.parent_code or "")
        if parent is not None:
            chapter_by_code[extracted.code].parent_id = parent.id

    item_by_code: dict[str, Any] = {}
    for extracted in items:
        chapter = chapter_by_code.get(extracted.chapter_code or "")
        item = ConstructionWorkItem(
            project_id=project_id,
            chapter_id=chapter.id if chapter is not None else None,
            code=extracted.code,
            description=extracted.description,
            unit=extracted.unit,
            quantity=extracted.quantity,
            unit_price=extracted.unit_price,
            total_price=extracted.total_price,
            zone=extracted.zone,
            floor=extracted.floor,
            room=extracted.room,
            document_id=document_id,
            source_method="ocr_text",
            confidence=extracted.confidence,
        )
        db.add(item)
        item_by_code[extracted.code] = item
    db.flush()
    for extracted in breakdowns:
        item = item_by_code.get(extracted.work_item_code)
        if item is None:
            continue
        db.add(
            WorkItemBreakdown(
                work_item_id=item.id,
                length_m=extracted.length_m,
                width_m=extracted.width_m,
                height_m=extracted.height_m,
                units=extracted.units,
                formula=extracted.formula,
                computed_quantity=extracted.computed_quantity,
                description=extracted.description,
            )
        )


def _validate_result(
    result: PipelineResult,
    manifest: dict[str, Any],
    *,
    is_plan: bool,
    is_memory: bool,
) -> None:
    from app.services.validation import (
        validate_memory_against_manifest,
        validate_plan_against_manifest,
    )

    if is_plan:
        validation = validate_plan_against_manifest(
            result._plan_validation_payload or {"document_type": result.document_type},
            manifest,
        )
        result.validation_score = validation.score
    elif is_memory:
        validation = validate_memory_against_manifest(
            result._memory_sections,
            result._memory_specs,
            manifest,
        )
        result.validation_score = validation.score


def _count_sections(sections: list[Any]) -> int:
    return len(sections) + sum(_count_sections(section.children) for section in sections)
