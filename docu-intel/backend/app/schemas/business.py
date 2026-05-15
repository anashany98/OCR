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

    model_config = {"from_attributes": True}


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
