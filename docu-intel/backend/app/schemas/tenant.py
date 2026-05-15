from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.documents import DocumentRead


class HotelChainCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_active: bool = True


class HotelChainUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class HotelChainRead(BaseModel):
    id: int
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class HotelCreate(BaseModel):
    chain_id: int
    name: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=80)
    is_active: bool = True


class HotelUpdate(BaseModel):
    chain_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=80)
    is_active: bool | None = None


class HotelRead(BaseModel):
    id: int
    chain_id: int
    name: str
    code: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FolderRuleCreate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    pattern: str = Field(min_length=1, max_length=2048)
    match_type: str = "contains"
    chain_id: int | None = None
    hotel_id: int | None = None
    tags_json: list[str] = Field(default_factory=list)
    is_active: bool = True


class FolderRuleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    pattern: str | None = Field(default=None, min_length=1, max_length=2048)
    match_type: str | None = None
    chain_id: int | None = None
    hotel_id: int | None = None
    tags_json: list[str] | None = None
    is_active: bool | None = None


class FolderRuleRead(BaseModel):
    id: int
    name: str | None = None
    pattern: str
    match_type: str
    chain_id: int | None = None
    hotel_id: int | None = None
    tags_json: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FolderRulesApplyRequest(BaseModel):
    force: bool = False


class FolderRulesApplyResponse(BaseModel):
    matched: int
    assigned: int
    quarantined: int
    skipped: int


class DocumentAccessRead(BaseModel):
    document_id: int
    chain_id: int | None = None
    hotel_id: int | None = None
    assignment_status: str
    assignment_source: str
    tags_json: list[str]
    locked_manual: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentAccessUpdate(BaseModel):
    chain_id: int | None = None
    hotel_id: int | None = None
    assignment_status: str | None = None
    assignment_source: str | None = "manual"
    tags_json: list[str] | None = None
    locked_manual: bool | None = True


class AccessGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    description: str | None = None
    permissions_json: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class AccessGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = None
    permissions_json: dict[str, Any] | None = None
    is_active: bool | None = None


class AccessGroupRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    permissions_json: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AccessGroupMemberUpsert(BaseModel):
    principal_type: str = Field(pattern="^(user|technician)$")
    principal_id: str = Field(min_length=1, max_length=180)


class AccessGroupMemberRead(BaseModel):
    id: int
    group_id: int
    principal_type: str
    principal_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class QuarantineDocumentRead(DocumentRead):
    access_metadata: DocumentAccessRead | None = None


class SensitiveTagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    is_active: bool = True


class SensitiveTagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    is_active: bool | None = None


class SensitiveTagRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
