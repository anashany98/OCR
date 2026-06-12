from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClassificationSuggestionCreate(BaseModel):
    document_id: int
    integration_client_id: int | None = None
    suggestion_type: Literal[
        "classification_correction", "entity_link", "classification_rule", "quality_feedback"
    ]
    suggested_document_type: str | None = None
    current_document_type: str | None = None
    target_document_id: int | None = None
    pattern_value: str | None = None
    target_action: Literal["classify_as", "extract", "link"] | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str
    evidence: dict[str, Any] | None = None
    status: Literal["pending", "approved", "rejected", "applied"] = "pending"


class ClassificationSuggestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    integration_client_id: int | None
    suggestion_type: str
    suggested_document_type: str | None
    current_document_type: str | None
    target_document_id: int | None
    pattern_value: str | None
    target_action: str | None
    confidence: float
    reason: str
    evidence: dict[str, Any] | None
    status: Literal["pending", "approved", "rejected", "applied"]
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    applied_at: datetime | None
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _map_evidence_json(cls, values: dict[str, Any]) -> dict[str, Any]:
        if "evidence_json" in values and "evidence" not in values:
            values["evidence"] = values.pop("evidence_json")
        return values


class ClassificationSuggestionReview(BaseModel):
    status: Literal["approved", "rejected"]
    reason: str | None = None


class LearnedPatternRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pattern_type: str
    pattern_value: str
    target_class: str | None
    target_action: str
    confidence: float
    source_suggestion_id: int | None
    status: Literal["active", "disabled", "pending"]
    applied_count: int
    last_applied_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LearnedPatternUpdate(BaseModel):
    status: Literal["active", "disabled"] | None = None


class ImprovementCandidate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    filename: str | None
    document_type: str | None
    current_status: str
    reason: str
    suggestion_type: str | None = None
    confidence: float | None = None


class ImprovementCandidatesResponse(BaseModel):
    candidates: list[ImprovementCandidate]
    total: int
