"""PP-Structure / layout_parsing engine (GPU-only) — adapter delegate.

Heavyweight document analysis pipeline. Runs layout detection (RT-DETR-H,
17 classes), text detection + recognition (PP-OCRv6), seal recognition,
and table recognition (SLANet_plus) in a single pass. Returns both the
flat text and the layout type of every region, so the cascade can
preserve "this block is a table" / "this is a figure" semantics all the
way to ``DocumentBlock.block_type``.

**GPU-only.** PaddlePaddle 3.x's PIR executor hits
``NotImplementedError: ConvertPirAttribute2RuntimeAttribute`` on the
layout_parsing pipeline when run on CPU. The engine refuses to
instantiate on CPU and tells the caller to use the PaddleOCR fallback
instead. This is by design — the cascade's Tier 3 only fires on GPU
workers.

**Lazy init.** The first ``extract()`` call downloads ~500 MB of models
from HuggingFace into ``$HOME/.paddlex/official_models`` and compiles
the Paddle inference graphs (~5-10 s). Subsequent calls are ~0.5-2 s
per page on an RTX 4070.

Install: ``pip install 'paddlex[ocr]==3.7.1'`` (only on the GPU image).

The :class:`PPStructureEngine` is now a thin wrapper around
:class:`app.ocr.structure_adapter.StructureAdapter`. The engine keeps
the same public surface (:pyattr:`name` == ``"pp_structure"``,
:meth:`extract`) and the ``_pipeline`` cached property (kept as a
backwards-compatible alias for tests).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from app.core.config import settings
from app.ocr.base import OCRResult
from app.ocr.preprocess import preprocess_for_paddle
from app.ocr.structure_adapter import StructureAdapter
from app.services.metrics import track_ocr_duration


# Skip the HuggingFace connectivity probe that adds ~2 s to first init.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


class PPStructureEngine:
    """PaddleX ``layout_parsing`` pipeline (PP-StructureV3 / V2 fallback).

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
                "3.x PIR executor crashes on CPU with "
                "'NotImplementedError: ConvertPirAttribute2RuntimeAttribute'. "
                "Use PaddleOCR (Tier 2) on CPU workers."
            )
        self.device = device
        self.lang = lang
        self._adapter = StructureAdapter(
            device=device,
            export_markdown=settings.pp_structure_export_markdown,
            export_json=settings.pp_structure_export_json,
            log_runtime_info=settings.pp_structure_log_runtime_info,
            settings=settings,
        )

    @property
    def _pipeline(self):
        """Backwards-compatible accessor used by the legacy tests."""
        return self._adapter._holder.get()

    def extract(self, image_path: Path) -> OCRResult:
        start = time.perf_counter()
        ocr_path = preprocess_for_paddle(image_path)
        try:
            result = self._adapter.run(ocr_path)
        finally:
            track_ocr_duration(time.perf_counter() - start)
        if result.engine != self.name:
            result.engine = self.name
        return result


__all__ = ["PPStructureEngine", "StructureAdapter"]
