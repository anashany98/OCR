from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IntegrationToolDefinition(BaseModel):
    name: str
    description: str
    arguments_schema: dict[str, Any]
    scopes: list[str] = Field(default_factory=lambda: ["read"])


class IntegrationManifest(BaseModel):
    version: str
    rules: list[str]
    tools: list[IntegrationToolDefinition]


class IntegrationSessionCreateRequest(BaseModel):
    budget_code: str = Field(min_length=1, max_length=120)


class IntegrationSessionCreateResponse(BaseModel):
    session_token: str
    budget_code: str
    budget_scope_id: int
    expires_in: int
    can_see_amounts: bool


class IntegrationToolExecuteRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    sandbox: bool = False


class IntegrationSource(BaseModel):
    document_id: int | None = None
    filename: str | None = None
    page_number: int | None = None
    block_id: int | None = None
    excerpt: str | None = None
    confidence: float | None = None


class IntegrationToolExecuteResponse(BaseModel):
    request_id: str
    tool: str
    technician_id: str
    data: dict[str, Any] | list[dict[str, Any]]
    sources: list[IntegrationSource] = Field(default_factory=list)
    confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)
    redactions: list[str] = Field(default_factory=list)
    scope: dict[str, Any] = Field(default_factory=dict)


class IntegrationDocumentStatus(BaseModel):
    id: int
    original_filename: str
    document_type: str
    status: str
    confidence: float | None = None
    page_count: int | None = None
    error_message: str | None = None
    created_at: datetime
    processed_at: datetime | None = None

    model_config = {"from_attributes": True}


class IntegrationJobStatus(BaseModel):
    id: int
    document_id: int
    job_type: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    retries: int

    model_config = {"from_attributes": True}


class IntegrationUploadResponse(BaseModel):
    document: IntegrationDocumentStatus
    job: IntegrationJobStatus | None = None
