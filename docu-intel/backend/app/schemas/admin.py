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


class QueueStatusRead(BaseModel):
    ingestion_paused: bool
    pending_jobs: int
    processing_jobs: int
    max_pending_jobs: int
    backpressure_active: bool
    queues: dict[str, dict[str, int]]


class JobActionResponse(BaseModel):
    id: int
    document_id: int
    job_type: str
    status: str
    error_message: str | None = None

    model_config = {"from_attributes": True}


class IntegrationClientRead(BaseModel):
    id: int
    name: str
    scopes_json: list[str]
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class IntegrationClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["read"])
    is_active: bool = True


class IntegrationClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    scopes: list[str] | None = None
    is_active: bool | None = None


class IntegrationClientSecretRead(IntegrationClientRead):
    api_key: str | None = None


class SystemHealthRead(BaseModel):
    status: str
    checks: dict[str, dict[str, Any]]


class OcrReviewBlockRead(BaseModel):
    id: int
    block_type: str
    text: str | None
    bbox_x1: float | None
    bbox_y1: float | None
    bbox_x2: float | None
    bbox_y2: float | None
    confidence: float | None
    source_engine: str | None


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
    quality_status: str
    quality_score: float | None
    quality_flags_json: list[str]
    text: str
    text_excerpt: str
    blocks: list[OcrReviewBlockRead]
    preview_url: str | None
    created_at: datetime


class OcrReviewPageUpdate(BaseModel):
    review_status: Literal["pending", "approved", "rejected"]
    review_notes: str | None = Field(default=None, max_length=2000)


class WorkInboxItemRead(BaseModel):
    kind: str
    severity: str
    title: str
    description: str
    document_id: int | None = None
    page_id: int | None = None
    job_id: int | None = None
    action_url: str | None = None
    status: str | None = None
    created_at: datetime | None = None


class WorkInboxActionRequest(BaseModel):
    action: Literal[
        "retry_failed_jobs",
        "approve_high_confidence_ocr",
        "reprocess_low_quality",
        "mark_duplicates_reviewed",
    ]
    limit: int = Field(default=100, ge=1, le=1000)
    min_confidence: float = Field(default=0.85, ge=0, le=1)


class WorkInboxActionResponse(BaseModel):
    action: str
    matched: int
    updated: int
    enqueued: int
    job_ids: list[int] = Field(default_factory=list)


class ProductionChecklistItem(BaseModel):
    key: str
    title: str
    status: Literal["ok", "warning", "error"]
    description: str
    action_url: str | None = None


class ProductionChecklistResponse(BaseModel):
    items: list[ProductionChecklistItem]


class RulePreviewRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)
    pattern: str = Field(min_length=1, max_length=512)
    match_type: Literal["contains", "glob", "regex"] = "contains"
    tags_json: list[str] = Field(default_factory=list)


class RulePreviewResponse(BaseModel):
    matches: bool
    normalized_path: str
    normalized_pattern: str
    match_type: str
    specificity: int
    tags_json: list[str]


class IntegrationSandboxExecuteRequest(BaseModel):
    client_id: int = Field(ge=1)
    technician_id: str = Field(min_length=1, max_length=120)
    technician_name: str | None = Field(default=None, max_length=120)
    tool: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)


class RedactionPreviewRequest(BaseModel):
    principal_type: Literal["user", "technician"]
    principal_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=5000)


class RedactionPreviewResponse(BaseModel):
    principal_type: str
    principal_id: str
    can_view_prices: bool
    redacted_text: str
    redactions: list[str]


class EffectiveAccessRead(BaseModel):
    principal_type: str
    principal_id: str
    role: str
    allow_all_hotels: bool
    chain_ids: list[int]
    hotel_ids: list[int]
    denied_tags: list[str]
    allowed_document_types: list[str]
    allow_unassigned_documents: bool
    can_view_prices: bool
    can_search_budgets: bool
    redacted_fields: list[str]
    group_count: int = 0


class BulkTagsRequest(BaseModel):
    document_ids: list[int] = Field(min_length=1, max_length=1000)
    add_tags: list[str] = Field(default_factory=list)
    remove_tags: list[str] = Field(default_factory=list)


class BulkTagsResponse(BaseModel):
    matched: int
    updated: int
    document_ids: list[int]
    tags_by_document: dict[str, list[str]]


class QualityRulesRead(BaseModel):
    low_ocr_threshold: float
    sensitive_tags: list[str]
    business_rules: list[str]
    descriptions: dict[str, str]


class QualitySummaryRead(BaseModel):
    rules: dict[str, dict[str, Any]]
    by_quality_status: dict[str, int]


class QualityRecalculateRequest(BaseModel):
    limit: int = Field(default=500, ge=1, le=10000)


class QualityRecalculateResponse(BaseModel):
    matched: int
    updated: int
    needs_review: int


class ProductionReadinessCheck(BaseModel):
    key: str
    status: Literal["ok", "warning", "error"]
    description: str


class ProductionReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    checks: list[ProductionReadinessCheck]


class StorageIntegrityResponse(BaseModel):
    checked_documents: int
    missing_files: int
    orphan_files: int
    hash_mismatches: int
    missing_file_samples: list[dict[str, Any]]
    orphan_file_samples: list[str]


class PaginatedDocumentsResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


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
