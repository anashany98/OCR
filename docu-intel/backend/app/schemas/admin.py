from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AdminStats(BaseModel):
    documents_total: int
    documents_processed: int
    documents_pending: int
    documents_failed: int
    documents_needs_review: int
    duplicates: int
    ocr_errors: int
    accepted_budgets_without_order: int
    plans_without_valid_scale: int


class AdminAlertRead(BaseModel):
    key: str
    title: str
    description: str
    severity: str
    count: int
    action_url: str

    model_config = {"from_attributes": True}


class ProcessingMetricsRead(BaseModel):
    documents_by_status: dict[str, int]
    documents_by_type: dict[str, int]
    jobs_by_status: dict[str, int]
    audit_events_total: int


class OcrReviewPageRead(BaseModel):
    document_id: int
    original_filename: str
    document_type: str
    status: str
    confidence: float | None
    page_id: int
    page_number: int
    ocr_confidence: float | None
    review_status: str
    review_notes: str | None
    reviewed_at: datetime | None
    reviewed_by_id: int | None
    text: str
    text_excerpt: str
    preview_url: str | None
    created_at: datetime


class OcrReviewPageUpdate(BaseModel):
    review_status: Literal["pending", "approved", "rejected"]
    review_notes: str | None = Field(default=None, max_length=2000)


class AuditLogRead(BaseModel):
    id: int
    user_id: int | None
    action: str
    entity_type: str | None
    entity_id: int | None
    details_json: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BudgetScopeCreate(BaseModel):
    budget_code: str = Field(min_length=1, max_length=120)
    source_path: str | None = None
    local_path: str | None = None
    display_name: str | None = None
    status: str = "pending"


class BudgetScopeRead(BaseModel):
    id: int
    budget_code: str
    source_path: str | None
    local_path: str | None
    display_name: str | None
    status: str
    total_files: int
    processed_files: int
    failed_files: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiClientBudgetScopeUpsert(BaseModel):
    client_id: int = Field(ge=1)
    can_query: bool = True
    can_see_amounts: bool = False


class ApiClientBudgetScopeRead(BaseModel):
    id: int
    api_client_id: int
    budget_scope_id: int
    can_query: bool
    can_see_amounts: bool
    created_at: datetime

    model_config = {"from_attributes": True}
