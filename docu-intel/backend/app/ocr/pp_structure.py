"""PP-Structure / layout_parsing engine (GPU-only, PaddleX 3.x).

Heavyweight document analysis pipeline. Runs layout detection (RT-DETR-H,
17 classes), text detection + recognition (PP-OCRv4), seal recognition,
and table recognition (SLANet_plus) in a single pass. Returns both the
flat text and the layout type of every region, so the cascade can
preserve "this block is a table" / "this is a figure" semantics all the
way to ``DocumentBlock.block_type``.

**GPU-only.** PaddlePaddle 3.3.x's PIR executor hits
``NotImplementedError: ConvertPirAttribute2RuntimeAttribute`` on the
layout_parsing pipeline when run on CPU. The engine refuses to
instantiate on CPU and tells the caller to use the PaddleOCR fallback
instead. This is by design — the cascade's Tier 3 only fires on GPU
workers.

**Lazy init.** The first ``extract()`` call downloads ~500 MB of models
from HuggingFace into ``$HOME/.paddlex/official_models`` and compiles
the Paddle inference graphs (~5-10 s). Subsequent calls are ~0.5-2 s
per page on an RTX 4070.

Install: ``pip install 'paddlex[ocr]==3.5.2'`` (only on the GPU image).
"""
from __future__ import annotations

import os
import threading
import time
from functools import cached_property
from pathlib import Path

from app.ocr.base import BaseOCREngine, OCRBlock, OCRResult
from app.services.metrics import track_ocr_duration


# Skip the HuggingFace connectivity probe that adds ~2 s to first init.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


class PPStructureEngine:
    """PaddleX ``layout_parsing`` pipeline (PP-Structure renamed in 3.x).

    Implements the :class:`BaseOCREngine` protocol. Each block in the
    returned :class:`OCRResult` carries a ``block_type`` drawn from
    PaddleX's 17-class layout taxonomy (``text``, ``doc_title``,
    ``table``, ``figure``, ``reference``, etc.).
    """

    name: str = "pp_structure"

    def __init__(self, device: str = "gpu", lang: str = "es") -> None:
        if device != "gpu":
            raise RuntimeError(
                "PP-Structure / layout_parsing is GPU-only: the PaddlePaddle "
                "3.3.x PIR executor crashes on CPU with "
                "'NotImplementedError: ConvertPirAttribute2RuntimeAttribute'. "
                "Use PaddleOCR (Tier 2) on CPU workers."
            )
        self.device = device
        self.lang = lang

    @cached_property
    def _pipeline(self):
        """Lazily build the PaddleX pipeline on first use (thread-safe)."""
        result: list[object] = [None]
        error: list[BaseException | None] = [None]

        def _init():
            try:
                from paddlex import create_pipeline

                result[0] = create_pipeline(
                    pipeline="layout_parsing",
                    device=self.device,
                )
            except BaseException as exc:  # noqa: BLE001 — surface anything to the caller
                error[0] = exc

        t = threading.Thread(target=_init, daemon=True)
        t.start()
        t.join(timeout=300)  # first init can take 1-2 min (model download + compile)

        if t.is_alive():
            raise TimeoutError("PPStructure pipeline init timed out after 300s")
        if error[0] is not None:
            raise error[0]
        return result[0]

    def extract(self, image_path: Path) -> OCRResult:
        start = time.perf_counter()
        try:
            results = list(self._pipeline.predict(str(image_path)))
        except Exception:
            track_ocr_duration(time.perf_counter() - start)
            raise

        if not results:
            track_ocr_duration(time.perf_counter() - start)
            return OCRResult(text="", confidence=None, blocks=[], engine=self.name)

        result = results[0]
        # ``LayoutParsingResult.json`` is the canonical structured payload.
        data = result.json if hasattr(result, "json") else {}
        res = data.get("res", data) if isinstance(data, dict) else {}
        parsing_list = res.get("parsing_res_list", []) if isinstance(res, dict) else []

        blocks: list[OCRBlock] = []
        confidences: list[float] = []
        text_parts: list[str] = []

        for region in parsing_list:
            if not isinstance(region, dict):
                continue
            content = (region.get("block_content") or "").strip()
            if not content:
                continue
            bbox = _as_bbox(region.get("block_bbox"))
            block_type = region.get("block_label")
            # ``doc_title`` is a specialisation of plain text — keep it as
            # a distinct block type so the admin breakdown can show it.
            blocks.append(
                OCRBlock(
                    text=content,
                    confidence=None,
                    bbox=bbox,
                    block_type=block_type,
                )
            )
            text_parts.append(content)

        # Layout parsing doesn't expose per-block confidence the way PaddleOCR
        # does; surface the top-level overall_ocr_res confidence if present.
        overall_ocr = res.get("overall_ocr_res") if isinstance(res, dict) else None
        if isinstance(overall_ocr, dict):
            scores = overall_ocr.get("rec_scores") or []
            try:
                confidences = [float(s) for s in scores if s is not None]
            except (TypeError, ValueError):
                confidences = []

        avg_conf = sum(confidences) / len(confidences) if confidences else None
        track_ocr_duration(time.perf_counter() - start)
        return OCRResult(
            text="\n".join(text_parts),
            confidence=avg_conf,
            blocks=blocks,
            engine=self.name,
        )


def _as_bbox(raw: object) -> tuple[float, float, float, float] | None:
    """Coerce a PaddleX bbox ``[x1, y1, x2, y2]`` into a 4-tuple of floats."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        return float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])
    except (TypeError, ValueError):
        return None


__all__ = ["PPStructureEngine"]
