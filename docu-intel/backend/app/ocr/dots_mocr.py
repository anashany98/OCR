from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.ocr.base import OCRBlock, OCRResult


@dataclass(frozen=True)
class DotsMOCRConfig:
    enabled: bool = False
    endpoint: str | None = None
    api_key: str | None = None
    timeout_seconds: float = 120.0


class DotsMOCREngine:
    name = "dots_mocr"

    def __init__(self, config: DotsMOCRConfig) -> None:
        self.config = config

    def extract(self, image_path: Path) -> OCRResult:
        if not self.config.enabled:
            raise RuntimeError("dots.mocr integration is disabled")
        if not self.config.endpoint:
            raise RuntimeError("dots.mocr endpoint is not configured")

        payload = {
            "filename": image_path.name,
            "image_base64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else None
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(self.config.endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        text = str(data.get("text") or "").strip()
        confidence = _coerce_confidence(data.get("confidence"))
        blocks = _parse_blocks(data.get("blocks"))
        if not blocks and text:
            blocks = [OCRBlock(text=text, confidence=confidence, bbox=None, block_type=None)]
        return OCRResult(text=text, confidence=confidence, blocks=blocks, engine=self.name)


def _coerce_confidence(value: object) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _parse_blocks(raw_blocks: object) -> list[OCRBlock]:
    if not isinstance(raw_blocks, list):
        return []
    blocks: list[OCRBlock] = []
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        blocks.append(
            OCRBlock(
                text=text,
                confidence=_coerce_confidence(raw.get("confidence")),
                bbox=_coerce_bbox(raw.get("bbox")),
                block_type=str(raw["block_type"]) if raw.get("block_type") else None,
            )
        )
    return blocks


def _coerce_bbox(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(part) for part in value)
    except (TypeError, ValueError):
        return None
    return (x1, y1, x2, y2)


__all__ = ["DotsMOCRConfig", "DotsMOCREngine"]
