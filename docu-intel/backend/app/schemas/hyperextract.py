"""Hyper-Extract — API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class HyperExtractEnvelope(BaseModel):
    """The canonical envelope returned by the service and the routes."""

    enabled: bool
    status: Literal["disabled", "pending", "success", "failed", "skipped"] = "disabled"
    document_id: int | str | None = None
    document_type: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    entities: list[Any] = Field(default_factory=list)
    relations: list[Any] = Field(default_factory=list)
    raw_output: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    latency_ms: int = 0
    error_message: str | None = None


class HyperExtractRequest(BaseModel):
    """POST body for ``POST /documents/{id}/extract`` and the retry route."""

    document_type: str | None = Field(
        default=None,
        description=(
            "Optional document type override (factura, albaran, contrato, "
            "presupuesto). When omitted the service uses "
            "settings.hyperextract_default_type."
        ),
    )
    force: bool = Field(
        default=False,
        description=(
            "When true, run even if HYPEREXTRACT_ENABLED=false. Useful "
            "for ops validation but disabled in production by default."
        ),
    )


class DocumentExtractionRead(BaseModel):
    """The persisted row shape used by GET endpoints."""

    id: int
    document_id: int
    document_type: str | None
    provider: str | None
    model: str | None
    status: str
    fields_json: dict[str, Any]
    entities_json: list[Any]
    relations_json: list[Any]
    warnings_json: list[str]
    raw_output_json: dict[str, Any] | None
    error_message: str | None
    latency_ms: int | None
    confidence: float | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
