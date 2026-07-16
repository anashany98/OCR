"""Versioned, deliberately small public schema for the internal OCR service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1"


class OvisOCR2Block(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["text", "table", "formula", "figure"]
    text: str
    bbox_norm: tuple[float, float, float, float] | None = None


class OvisOCR2Response(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    request_id: str
    model: str
    revision: str
    markdown: str
    blocks: list[OvisOCR2Block] = Field(default_factory=list)
    finish_reason: Literal["stop", "length", "error"]
    input_pixels: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    warnings: list[str] = Field(default_factory=list)


class OvisOCR2Readiness(BaseModel):
    status: Literal["ready", "loading", "failed"]
    model: str
    revision: str
    detail: str | None = None


__all__ = ["OvisOCR2Block", "OvisOCR2Readiness", "OvisOCR2Response", "SCHEMA_VERSION"]
