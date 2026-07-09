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

import concurrent.futures
import logging
import os
import time
from pathlib import Path

from app.ocr.base import OCRBlock, OCRResult
from app.services.metrics import track_ocr_duration

logger = logging.getLogger("app.ocr.pp_structure")

_PP_INIT_TIMEOUT_SECONDS: float = 120.0

# Process-level flag: prevents repeated init attempts after timeout.
# Like PaddleOCR's flag it auto-resets after a TTL so a transient spike
# (e.g. VRAM exhaustion, a one-off GPU context corruption) does not
# permanently disable Tier 3 for the lifetime of the worker process.
_PROCESS_INIT_FAILED_PP: bool = False
_PROCESS_INIT_FAILED_PP_AT: float = 0.0
_PROCESS_INIT_TTL_PP_SECONDS: float = 1800.0  # 30 minutes

# B7: skip the HuggingFace connectivity probe that adds ~2 s to first
# init. Set at import time so it runs exactly once per process, not once
# per PPStructureEngine instance.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def _is_pp_init_failed() -> bool:
    """Check if PP-Structure init is failed. Auto-reset after TTL."""
    global _PROCESS_INIT_FAILED_PP, _PROCESS_INIT_FAILED_PP_AT
    if not _PROCESS_INIT_FAILED_PP:
        return False
    if time.monotonic() - _PROCESS_INIT_FAILED_PP_AT > _PROCESS_INIT_TTL_PP_SECONDS:
        logger.info(
            "PP-Structure init failure TTL expired (%.0fs), allowing retry",
            _PROCESS_INIT_TTL_PP_SECONDS,
        )
        _PROCESS_INIT_FAILED_PP = False
        return False
    return True


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
        # B7: skip the HuggingFace connectivity probe that adds ~2 s to
        # first init. Applied at module level (below) so it runs exactly
        # once per process instead of per instance.
        self.device = device
        self.lang = lang
        # O6/M3: when the lazy init fails or times out the engine is
        # marked unavailable so subsequent calls raise a clear error
        # instead of re-entering the broken state (same convention as
        # PaddleOCR).
        self._init_failed: bool = False

    @property
    def _pipeline(self):
        """Lazily build the PaddleX pipeline on first use with timeout protection."""
        if _is_pp_init_failed() or getattr(self, "_init_failed", False):
            raise RuntimeError(
                "PP-Structure engine is unavailable: previous init attempt failed"
            )
        if not hasattr(self, "_pipeline_instance"):
            self._init_pipeline_with_timeout()
        return self._pipeline_instance

    def _init_pipeline_with_timeout(self):
        """Load the PaddleX pipeline with a timeout to prevent indefinite blocking."""
        try:
            from paddlex import create_pipeline
        except ImportError as err:
            self._init_failed = True
            raise RuntimeError(
                "paddlex is not installed. Install with: pip install 'paddlex[ocr]==3.5.2'"
            ) from err

        def _build():
            return create_pipeline(
                pipeline="layout_parsing",
                device=self.device,
                lang=self.lang,
            )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ppstructure-init"
        ) as executor:
            future = executor.submit(_build)
            try:
                self._pipeline_instance = future.result(timeout=_PP_INIT_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                global _PROCESS_INIT_FAILED_PP, _PROCESS_INIT_FAILED_PP_AT
                future.cancel()
                _PROCESS_INIT_FAILED_PP = True
                _PROCESS_INIT_FAILED_PP_AT = time.monotonic()
                self._init_failed = True
                logger.error(
                    "PP-Structure init timed out after %.0fs (device=%s, lang=%s). "
                    "Process marked — all future PP-Structure inits will skip.",
                    _PP_INIT_TIMEOUT_SECONDS, self.device, self.lang,
                )
                raise RuntimeError(
                    f"PP-Structure model init timed out after {_PP_INIT_TIMEOUT_SECONDS}s"
                ) from None
            except Exception:
                self._init_failed = True
                raise

    def extract(self, image_path: Path) -> OCRResult:
        start = time.perf_counter()
        # Use preprocess_adaptive to benefit from caching across tiers
        from app.ocr.preprocess import preprocess_adaptive
        ocr_path = preprocess_adaptive(image_path, engine=self.name)
        try:
            # PP-Structure predict() has no built-in timeout. Use a
            # disposable ThreadPoolExecutor — on timeout the pool
            # cleans up the thread (it becomes a zombie until the
            # GIL is released, same as paddle.py).
            from concurrent.futures import ThreadPoolExecutor
            from concurrent.futures import TimeoutError as FuturesTimeout

            result_holder: list = []
            exc_holder: list = []

            def _run_predict():
                try:
                    result_holder.extend(self._pipeline.predict(str(ocr_path)))
                except Exception as exc:  # noqa: BLE001
                    exc_holder.append(exc)

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_run_predict)
                try:
                    future.result(timeout=120)
                except FuturesTimeout as err:
                    future.cancel()
                    raise TimeoutError(
                        f"PP-Structure predict() timed out after 120s on {image_path.name}"
                    ) from err
            if exc_holder:
                raise exc_holder[0]
            results = result_holder
        except Exception:
            raise
        finally:
            if ocr_path != image_path:
                ocr_path.unlink(missing_ok=True)

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
