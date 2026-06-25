from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class WorkItemCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class WorkItemCommentRead(BaseModel):
    id: int
    work_item_id: int
    user_id: int | None
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkItemCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    document_id: int | None = None
    page_id: int | None = None
    job_id: int | None = None
    assignee_user_id: int | None = None
    due_at: datetime | None = None


class WorkItemUpdate(BaseModel):
    status: Literal["open", "in_progress", "resolved", "ignored"] | None = None
    priority: Literal["low", "normal", "high", "critical"] | None = None
    assignee_user_id: int | None = None
    due_at: datetime | None = None
    resolution_notes: str | None = None


class WorkItemRead(BaseModel):
    id: int
    kind: str
    title: str
    description: str
    priority: str
    status: str
    document_id: int | None
    page_id: int | None
    job_id: int | None
    assignee_user_id: int | None
    due_at: datetime | None
    resolution_notes: str | None
    resolved_at: datetime | None
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime
    comments: list[WorkItemCommentRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DocumentTimelineEventRead(BaseModel):
    id: int
    document_id: int
    event_type: str
    title: str
    description: str | None
    actor_user_id: int | None
    details_json: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class OcrRevisionCreate(BaseModel):
    corrected_text: str = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=2000)


class OcrRevisionRead(BaseModel):
    id: int
    page_id: int
    document_id: int
    original_text: str
    corrected_text: str
    reason: str | None
    created_by_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvoiceRead(BaseModel):
    id: int
    document_id: int
    invoice_number: str | None
    supplier_name: str | None
    client_name: str | None
    date: date_type | None
    total_amount: float | None
    currency: str | None
    related_order_id: int | None
    confidence: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvoiceCreate(BaseModel):
    document_id: int
    invoice_number: str | None = Field(default=None, max_length=120)
    supplier_name: str | None = Field(default=None, max_length=255)
    client_name: str | None = Field(default=None, max_length=255)
    date: date_type | None = None
    total_amount: float | None = None
    currency: str | None = "EUR"
    related_order_id: int | None = None
    confidence: float | None = None


class ReconciliationIssueUpdate(BaseModel):
    status: Literal["pending", "reviewed", "ignored"] | None = None
    resolution_notes: str | None = Field(default=None, max_length=2000)


class ReconciliationIssueRead(BaseModel):
    id: int
    kind: str
    severity: str
    status: str
    title: str
    description: str
    budget_id: int | None
    order_id: int | None
    invoice_id: int | None
    document_id: int | None
    expected_amount: float | None
    actual_amount: float | None
    resolution_notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SavedViewCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: str = Field(default="documents", max_length=80)
    filters_json: dict[str, Any] = Field(default_factory=dict)
    is_shared: bool = False


class SavedViewRead(SavedViewCreate):
    id: int
    user_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SavedSearchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1)
    mode: str = "hybrid"
    filters_json: dict[str, Any] = Field(default_factory=dict)


class SavedSearchRead(SavedSearchCreate):
    id: int
    user_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    event_type: str = Field(min_length=1, max_length=80)
    channel: Literal["email", "webhook", "teams"] = "webhook"
    target: str = Field(min_length=1, max_length=512)
    is_active: bool = True
    filters_json: dict[str, Any] = Field(default_factory=dict)


class NotificationRuleRead(NotificationRuleCreate):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminUserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=255)
    role: Literal["admin", "gestor", "operario", "auditor"] = "operario"
    password: str = Field(min_length=12, max_length=256)
    is_active: bool = True


class AdminUserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    role: Literal["admin", "gestor", "operario", "auditor"] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)


class AdminUserRead(BaseModel):
    id: int
    email: str
    name: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PlanMeasurementCreate(BaseModel):
    label: str = Field(min_length=1, max_length=180)
    page_number: int | None = None
    measurement_type: str = "distance"
    value_m: float | None = None
    ocr_value_m: float | None = None
    points_json: list[dict[str, Any]] = Field(default_factory=list)
    calibration_json: dict[str, Any] | None = None


class PlanMeasurementRead(PlanMeasurementCreate):
    id: int
    plan_id: int
    has_discrepancy: bool
    created_by_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
