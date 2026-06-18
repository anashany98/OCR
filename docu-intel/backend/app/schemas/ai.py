import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class AskRequest(BaseModel):
    question: str
    mode: str | None = None
    # Optional session id for in-conversation state. When the same id
    # is sent on consecutive turns, the assistant keeps the active
    # context (current budget / document / client) and the scope guard
    # can avoid cross-budget contamination. When omitted, the request
    # is treated as stateless and behaves exactly like the previous
    # version. Format: opaque string (typically a UUID4).
    session_id: str | None = None


class AIAnswerSourceRead(BaseModel):
    id: int
    answer_id: int
    document_id: int | None
    page_number: int | None
    block_id: int | None
    relevance_score: float | None
    excerpt: str | None

    model_config = {"from_attributes": True}


class AIAnswerRead(BaseModel):
    id: int
    question_id: int
    answer: str
    confidence: float | None
    model_name: str | None
    # Optional structured snapshot of the document the agent resolved
    # for this answer (entities + relations). Parsed from
    # `resolved_document_json` by the model_validator below.
    resolved_document: dict[str, Any] | None = None
    # Suggested follow-up questions (not persisted, generated on-the-fly).
    followups: list[str] = Field(default_factory=list)
    created_at: datetime
    sources: list[AIAnswerSourceRead] = Field(default_factory=list)

    model_config = {"from_attributes": True, "protected_namespaces": ()}

    @model_validator(mode="before")
    @classmethod
    def _parse_resolved_document_json(cls, data: Any) -> Any:
        # FastAPI hands us the SQLAlchemy AIAnswer object directly. Pull the
        # JSON blob out and expose it as a structured dict for the UI.
        raw = getattr(data, "resolved_document_json", None)
        if raw and isinstance(raw, str):
            try:
                data.resolved_document = json.loads(raw)
            except Exception:
                data.resolved_document = None
        return data


class AIQuestionRead(BaseModel):
    id: int
    user_id: int | None
    question: str
    created_at: datetime

    model_config = {"from_attributes": True}
