from __future__ import annotations

import logging
import time
from pathlib import Path

from app.ai.nuextract_client import NuExtractClient, run_async_blocking
from app.ocr.base import OCRBlock, OCRResult

logger = logging.getLogger("app.ocr.nuextract")


class NuExtractOCREngine:
    name = "nuextract3"

    def __init__(
        self,
        *,
        client: NuExtractClient | None = None,
        confidence: float = 0.75,
    ) -> None:
        self.client = client or NuExtractClient()
        self.confidence = max(0.0, min(1.0, float(confidence)))

    def extract(self, image_path: Path) -> OCRResult:
        started = time.perf_counter()
        logger.info("nuextract tier4 OCR started: image=%s", image_path.name)
        markdown = run_async_blocking(self.client.markdown_from_image(image_path))
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "nuextract tier4 OCR finished: image=%s latency_ms=%s markdown_len=%s",
            image_path.name,
            latency_ms,
            len(markdown),
        )
        blocks = []
        if markdown:
            blocks.append(
                OCRBlock(
                    text=markdown,
                    confidence=self.confidence,
                    bbox=None,
                    block_type="markdown",
                )
            )
        return OCRResult(
            text=markdown,
            confidence=self.confidence if markdown else 0.0,
            blocks=blocks,
            engine=self.name,
        )


__all__ = ["NuExtractOCREngine"]
