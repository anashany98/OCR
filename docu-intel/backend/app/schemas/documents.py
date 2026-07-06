from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DocumentRead(BaseModel):
    id: int
    original_filename: str
    stored_filename: str | None
    source_path: str | None
    file_hash: str
    mime_type: str | None
    extension: str | None
    file_size: int
    document_type: str
    status: str
    quality_status: str
    quality_score: float | None
    quality_flags_json: list[str]
    confidence: float | None
    page_count: int | None
    error_message: str | None
    duplicate_of_document_id: int | None
    created_at: datetime
    processed_at: datetime | None

    model_config = {"from_attributes": True}


class DocumentPageRead(BaseModel):
    id: int
    document_id: int
    page_number: int
    width: float | None
    height: float | None
    text: str | None
    image_path: str | None
    page_status: str
    ocr_confidence: float | None
    attempts: int
    error_message: str | None
    processing_time_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentBlockRead(BaseModel):
    id: int
    document_id: int
    page_id: int | None
    page_number: int | None
    block_type: str
    text: str | None
    bbox_x1: float | None
    bbox_y1: float | None
    bbox_x2: float | None
    bbox_y2: float | None
    confidence: float | None
    source_engine: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentEntityRead(BaseModel):
    id: int
    document_id: int
    entity_type: str
    entity_value: str
    normalized_value: str | None
    confidence: float | None
    page_number: int | None
    source_block_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UploadResponse(BaseModel):
    document: DocumentRead
    job_id: int | None


class BulkReprocessRequest(BaseModel):
    status: str | None = None
    document_type: str | None = None
    source_path_contains: str | None = None
    ids: list[int] | None = None
    quality_flags: list[str] | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    mode: Literal["full", "ocr", "text", "classification", "entities", "chunks", "embeddings"] = (
        "full"
    )


class BulkReprocessResponse(BaseModel):
    matched: int
    enqueued: int
    skipped: int
    job_ids: list[int]
    mode: str
