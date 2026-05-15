from datetime import datetime

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str
    mode: str | None = None


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
    created_at: datetime
    sources: list[AIAnswerSourceRead] = Field(default_factory=list)

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class AIQuestionRead(BaseModel):
    id: int
    user_id: int | None
    question: str
    created_at: datetime

    model_config = {"from_attributes": True}
