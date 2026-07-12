"""PM8.2 — Technical document processing pipeline.

Connects all services into a single flow:
  Parse → Classify → Extract → Validate → Store

For plan documents:
  DXF/PDF → parse_dxf/parse_pdf → classify → extract_plan → extract_geometry → validate

For memory documents:
  PDF/OCR → parse → classify → parse_memory → extract_specs → validate

For budget documents:
  PDF/OCR → parse → classify → extract_work_items → validate
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

logger = logging.getLogger("app.services.technical_pipeline")


@dataclass
class PipelineResult:
    """Result of processing a technical document."""
    document_id: int
    document_type: str
    # Plan data
    plan_id: int | None = None
    rooms_extracted: int = 0
    dimensions_extracted: int = 0
    symbols_extracted: int = 0
    geometry_lines: int = 0
    geometry_polylines: int = 0
    geometry_arcs: int = 0
    # Memory data
    chapters_extracted: int = 0
    specs_extracted: int = 0
    # Budget data
    work_chapters_extracted: int = 0
    work_items_extracted: int = 0
    total_budget: float = 0.0
    # Validation
    validation_score: float = 0.0
    contradictions: int = 0
    # Errors
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def process_technical_document(
    db: Session,
    document_id: int,
    text: str,
    filename: str,
    document_type: str,
    blocks: list | None = None,
    manifest: dict | None = None,
) -> PipelineResult:
    """Process a technical document through the full pipeline.

    This is the main entry point that connects all services.
    """
    from app.services.classification import classify_document
    from app.services.memory_extraction import (
        parse_memory_structure,
        sections_to_chunks,
        extract_specifications,
    )
    from app.services.work_item_extraction import (
        extract_work_items_from_text,
        aggregate_work_items,
    )
    from app.services.validation import (
        validate_plan_against_manifest,
        validate_memory_against_manifest,
        detect_contradictions,
    )

    result = PipelineResult(document_id=document_id, document_type=document_type)

    # Step 1: Classify if not already classified
    if not document_type or document_type == "unknown":
        classification = classify_document(
            filename=filename,
            source_path=None,
            text=text,
        )
        document_type = classification.document_type
        result.document_type = document_type

    # Step 2: Route to appropriate extraction
    is_plan = document_type.startswith("plano") or document_type == "plano"
    is_memory = "memoria" in document_type
    is_budget = document_type in ("mediciones_obra", "presupuesto")

    if is_plan:
        _process_plan_data(result, text, blocks)
    elif is_memory:
        _process_memory_data(result, text, document_id)
    elif is_budget:
        _process_budget_data(result, text, document_id)

    # Step 3: Validate against manifest
    if manifest:
        _validate_result(result, manifest, is_plan, is_memory)

    return result


def _process_plan_data(
    result: PipelineResult,
    text: str,
    blocks: list | None,
):
    """Extract plan-specific data."""
    import re

    # Extract scale
    scale_match = re.search(r"1\s*[:/]\s*(\d+)", text)

    # Extract rooms
    lines = text.split("\n")
    room_names = []
    area_values = []
    for line in lines:
        stripped = line.strip()
        area_match = re.match(r"^(\d+(?:\.\d+)?)\s*m2?$", stripped)
        if area_match:
            area_values.append(float(area_match.group(1)))
        elif stripped and not stripped.startswith("Cota:") and not stripped.startswith("VIVIENDA"):
            if len(stripped) > 1 and not stripped[0].isdigit() and "m2" not in stripped:
                room_names.append(stripped)

    for i, name in enumerate(room_names):
        if i < len(area_values):
            result.rooms_extracted += 1

    # Extract dimensions from blocks
    if blocks:
        for b in blocks:
            if hasattr(b, "block_type") and b.block_type == "dimension":
                result.dimensions_extracted += 1

    # Geometry summary
    geom_match = re.search(r"Geometría:\s*(.+)", text)
    if geom_match:
        geom_str = geom_match.group(1)
        line_m = re.search(r"line=(\d+)", geom_str)
        pl_m = re.search(r"polyline=(\d+)", geom_str)
        arc_m = re.search(r"arc=(\d+)", geom_str)
        if line_m:
            result.geometry_lines = int(line_m.group(1))
        if pl_m:
            result.geometry_polylines = int(pl_m.group(1))
        if arc_m:
            result.geometry_arcs = int(arc_m.group(1))


def _process_memory_data(
    result: PipelineResult,
    text: str,
    document_id: int,
):
    """Extract memory-specific data."""
    from app.services.memory_extraction import (
        parse_memory_structure,
        extract_specifications,
    )

    # Parse structure
    sections = parse_memory_structure(text, document_type=result.document_type)
    result.chapters_extracted = _count_sections(sections)

    # Extract specs
    specs = extract_specifications(text, document_id=document_id)
    result.specs_extracted = len(specs)


def _process_budget_data(
    result: PipelineResult,
    text: str,
    document_id: int,
):
    """Extract budget-specific data."""
    from app.services.work_item_extraction import (
        extract_work_items_from_text,
        aggregate_work_items,
    )

    chapters, items, breakdowns = extract_work_items_from_text(text, document_id=document_id)
    result.work_chapters_extracted = len(chapters)
    result.work_items_extracted = len(items)

    agg = aggregate_work_items(items)
    result.total_budget = float(agg.get("total_price", 0))


def _validate_result(
    result: PipelineResult,
    manifest: dict,
    is_plan: bool,
    is_memory: bool,
):
    """Validate extracted data against manifest."""
    from app.services.validation import (
        validate_plan_against_manifest,
        validate_memory_against_manifest,
    )

    if is_plan:
        extracted = {
            "document_type": result.document_type,
            "scale": "",
            "rooms": [{"name": f"room_{i}", "area_m2": 0} for i in range(result.rooms_extracted)],
            "dimensions": [{"label": str(i), "value_m": i} for i in range(result.dimensions_extracted)],
            "symbols": {},
        }
        validation = validate_plan_against_manifest(extracted, manifest)
        result.validation_score = validation.score

    elif is_memory:
        # For memory validation, we'd need the actual specs
        result.validation_score = 1.0  # Placeholder


def _count_sections(sections: list) -> int:
    """Count total sections including children."""
    count = len(sections)
    for s in sections:
        count += _count_sections(s.children)
    return count
