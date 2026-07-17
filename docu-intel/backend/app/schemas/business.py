from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class BudgetRead(BaseModel):
    id: int
    document_id: int
    budget_number: str | None
    client_name: str | None
    date: date | None
    total_amount: float | None
    currency: str | None
    status: str | None
    accepted_detected: bool
    confidence: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BudgetLineRead(BaseModel):
    id: int
    budget_id: int
    reference: str | None
    description: str | None
    quantity: float | None
    unit: str | None
    unit_price: float | None
    total_price: float | None
    confidence: float | None

    model_config = {"from_attributes": True}


class OrderRead(BaseModel):
    id: int
    document_id: int
    order_number: str | None
    supplier_name: str | None
    client_name: str | None
    date: date | None
    total_amount: float | None
    currency: str | None
    related_budget_id: int | None
    confidence: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrderLineRead(BaseModel):
    id: int
    order_id: int
    reference: str | None
    description: str | None
    quantity: float | None
    unit: str | None
    unit_price: float | None
    total_price: float | None
    confidence: float | None

    model_config = {"from_attributes": True}


class PlanRead(BaseModel):
    id: int
    document_id: int
    project_name: str | None
    scale_text: str | None
    scale_ratio: float | None
    scale_confidence: float | None
    unit: str | None
    has_valid_scale: bool
    source_format: str | None = None
    cad_unit: str | None = None
    cad_extents_json: dict[str, Any] | None = None
    cad_metadata_json: dict[str, Any] | None = None
    coordinate_transform_json: dict[str, Any] | None = None
    conversion_provenance_json: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PlanRoomRead(BaseModel):
    id: int
    plan_id: int
    name: str | None
    area_m2: float | None
    width_m: float | None
    length_m: float | None
    polygon_json: dict[str, Any] | None
    confidence: float | None
    source: str | None
    needs_review: bool

    model_config = {"from_attributes": True}


class PlanDimensionRead(BaseModel):
    id: int
    plan_id: int
    raw_text: str | None
    value: float | None
    unit: str | None
    value_m: float | None
    page_number: int | None
    bbox_x1: float | None
    bbox_y1: float | None
    bbox_x2: float | None
    bbox_y2: float | None
    confidence: float | None
    source_method: str | None = None
    source_entity_handle: str | None = None
    layer: str | None = None
    native_value: float | None = None
    native_unit: str | None = None
    unit_source: str | None = None
    coordinates_json: dict[str, Any] | None = None
    validation_status: str = "auto"
    needs_review: bool = False

    model_config = {"from_attributes": True}


class PlanCadEntityRead(BaseModel):
    id: int
    plan_id: int
    entity_handle: str | None
    entity_type: str
    layer: str | None
    layout: str | None
    geometry_json: dict[str, Any] | None
    properties_json: dict[str, Any] | None
    source_method: str
    confidence: float | None
    validation_status: str

    model_config = {"from_attributes": True}


class PlanSymbolRead(BaseModel):
    """P2 — A single symbol detected by the YOLO detector.

    ``source_model`` records which detector produced the row
    (e.g. ``SamirShabani/Architect``). Useful when the operator
    swaps the model and wants to filter stale rows out of the
    response.
    """

    id: int
    plan_id: int
    symbol_class: str
    confidence: float
    page_number: int | None
    bbox_x1: float | None
    bbox_y1: float | None
    bbox_x2: float | None
    bbox_y2: float | None
    source_model: str | None

    model_config = {"from_attributes": True}


class PlanSymbolSummary(BaseModel):
    """P2 — Counts of detected symbols grouped by class.

    Returned by the ``/plans/{id}/symbols/summary`` endpoint so the
    frontend can render a single number per symbol type without
    downloading the full list.
    """

    plan_id: int
    counts: dict[str, int]
    total: int
    source_model: str | None


class PlanScaleUpdate(BaseModel):
    scale_text: str | None = None
    scale_ratio: float | None = None
    scale_confidence: float | None = None
    unit: str | None = None
    has_valid_scale: bool | None = None


class PlanRoomUpdate(BaseModel):
    name: str | None = None
    area_m2: float | None = None
    width_m: float | None = None
    length_m: float | None = None
    polygon_json: dict[str, Any] | None = None
    confidence: float | None = None
    source: str | None = None
    needs_review: bool | None = None


class PlanRoomCreate(BaseModel):
    """Payload for ``POST /plans/{id}/rooms``. The polygon is the user-drawn
    closed shape on top of the rendered page; the rest are derived or
    manually entered."""

    name: str | None = None
    area_m2: float | None = None
    width_m: float | None = None
    length_m: float | None = None
    polygon_json: dict[str, Any] | None = None
    page_number: int | None = None
    source: str | None = "manual"
    needs_review: bool | None = False
    confidence: float | None = None


class PlanDimensionCreate(BaseModel):
    raw_text: str | None = None
    value: float | None = None
    unit: str | None = "m"
    value_m: float | None = None
    page_number: int | None = None
    bbox_x1: float | None = None
    bbox_y1: float | None = None
    bbox_x2: float | None = None
    bbox_y2: float | None = None
    confidence: float | None = None


class PlanBulkUpdate(BaseModel):
    """Single save action: replace the working set of rooms and/or
    dimensions for a plan, and optionally update its scale + project
    metadata. Used by the annotation editor's "Save" button."""

    rooms: list[PlanRoomCreate] | None = None
    dimensions: list[PlanDimensionCreate] | None = None
    scale_text: str | None = None
    scale_ratio: float | None = None
    unit: str | None = None
    has_valid_scale: bool | None = None
    project_name: str | None = None


class PlanVisionSuggestionRequest(BaseModel):
    page_number: int = 1


class PlanVisionSuggestion(BaseModel):
    """One room the vision LLM thinks it sees on the plano page."""

    name: str
    bbox: list[float]  # [x1, y1, x2, y2] in image pixels
    confidence: float | None = None
    rationale: str | None = None


class PlanVisionSuggestionResponse(BaseModel):
    project_name: str | None = None
    scale_text: str | None = None
    rooms: list[PlanVisionSuggestion]
    model: str | None = None
