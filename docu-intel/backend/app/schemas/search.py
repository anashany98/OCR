from pydantic import BaseModel, Field


class SearchResultRead(BaseModel):
    document_id: int
    original_filename: str
    document_type: str
    status: str
    page_number: int | None
    block_id: int | None
    score: float
    excerpt: str
    ocr_confidence: float | None
    source_type: str = "text"


class SemanticSearchRequest(BaseModel):
    query: str
    filters: dict | None = None
    limit: int = Field(default=10, ge=1, le=50)


class HybridSearchRequest(BaseModel):
    query: str
    filters: dict | None = None
    limit: int = Field(default=10, ge=1, le=50)


class ExportFormat(str):
    CSV = "csv"
    JSON = "json"
