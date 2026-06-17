"""PP-Structure / PaddleX compatibility adapter (3.x → 3.7.1 / V3).

This module is the **only** place in the codebase that imports
``paddlex``. The :class:`StructureAdapter` exposes a single
``run(image_path) -> OCRResult`` method and hides three things from the
rest of the codebase:

1. **PPStructureV3 vs. PaddleX fallback.** PaddleX 3.7.1 may ship a
   ``PPStructureV3`` class directly; older 3.x versions only expose
   ``paddlex.create_pipeline("layout_parsing")``. The adapter tries
   ``PPStructureV3`` first when the profile requests it, then falls
   back to ``create_pipeline`` automatically. Operators can force
   the fallback via ``settings.pp_structure_force_paddlex_fallback``.

2. **Output format drift.** PaddleX has shipped at least three shapes
   over the years: ``LayoutParsingResult.json`` with
   ``parsing_res_list``, a list of regions with ``block_bbox`` /
   ``block_label`` / ``block_content`` attributes, and (in newer
   versions) a flat ``layout_parsing_res_list`` with markdown export.
   :func:`normalize_structure_output` accepts every shape we have seen
   and returns the canonical :class:`OCRBlock` list.

3. **GPU-only enforcement.** The PP-Structure / layout_parsing
   pipeline crashes on CPU in PaddlePaddle 3.x with
   ``ConvertPirAttribute2RuntimeAttribute``. The adapter refuses to
   instantiate when ``device != "gpu"`` so the failure happens at
   boot, not on the first real document.

The adapter is intentionally test-friendly: the constructor accepts
an ``engine_factory`` callable so unit tests can pass a mock without
importing PaddleX.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from app.ocr.base import OCRBlock, OCRResult
from app.ocr.model_registry import StructureProfile, resolve_structure_pipeline


logger = logging.getLogger("app.ocr.structure_adapter")


# Skip the HuggingFace connectivity probe that adds ~2s to first init.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _as_bbox(raw: Any) -> tuple[float, float, float, float] | None:
    """Coerce a PaddleX bbox ``[x1, y1, x2, y2]`` into a 4-tuple of floats."""
    if raw is None:
        return None
    if hasattr(raw, "tolist") and callable(raw.tolist):
        raw = raw.tolist()
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        return float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Output normalisation
# ---------------------------------------------------------------------------


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _extract_regions(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Pull the list of region dicts out of any known PaddleX payload shape."""
    res = payload.get("res") if isinstance(payload, Mapping) else None
    if not isinstance(res, Mapping):
        return []
    for key in (
        "parsing_res_list",
        "layout_parsing_res_list",
        "layout_res_list",
        "regions",
    ):
        value = res.get(key)
        if isinstance(value, list):
            return [r for r in value if isinstance(r, Mapping)]
    return []


def _extract_overall_scores(payload: Mapping[str, Any]) -> list[float]:
    res = payload.get("res") if isinstance(payload, Mapping) else None
    if not isinstance(res, Mapping):
        return []
    overall = res.get("overall_ocr_res")
    if not isinstance(overall, Mapping):
        return []
    scores = overall.get("rec_scores") or overall.get("rec_score") or []
    out: list[float] = []
    for s in scores:
        try:
            out.append(float(s))
        except (TypeError, ValueError):
            continue
    return out


def _extract_markdown(payload: Mapping[str, Any]) -> str | None:
    res = payload.get("res") if isinstance(payload, Mapping) else None
    if not isinstance(res, Mapping):
        return None
    for key in ("markdown", "md", "layout_parsing_markdown"):
        value = res.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, Mapping):
            text = value.get("text") or value.get("markdown")
            if isinstance(text, str) and text.strip():
                return text
    return None


def _extract_raw_json(payload: Any) -> Mapping[str, Any] | None:
    if isinstance(payload, Mapping):
        return payload
    return None


def normalize_structure_output(result: Any) -> tuple[list[OCRBlock], float | None, str | None]:
    """Convert any supported PaddleX shape into ``(blocks, confidence, markdown)``.

    The function returns:

    * ``blocks`` — list of :class:`OCRBlock` (text + bbox + block_type)
    * ``confidence`` — float or ``None``
    * ``markdown`` — string or ``None`` when the version exposes one
    """
    if result is None:
        return [], None, None

    # LayoutParsingResult.json canonical path (3.x)
    payload_obj: Any = None
    if hasattr(result, "json"):
        try:
            payload_obj = result.json
        except Exception as exc:
            logger.debug("structure_adapter: result.json raised %s", exc)
            payload_obj = None
    if payload_obj is None and isinstance(result, Mapping):
        payload_obj = result
    if payload_obj is None:
        # Object-style result (older PaddleX): walk attributes.
        content = getattr(result, "block_content", None)
        if content is not None:
            bbox = _as_bbox(getattr(result, "block_bbox", None))
            label = getattr(result, "block_label", None)
            block = OCRBlock(
                text=_coerce_str(content).strip(),
                confidence=None,
                bbox=bbox,
                block_type=str(label) if label else None,
            )
            return ([block] if block.text else [], None, None)
        return [], None, None

    regions = _extract_regions(payload_obj)
    blocks: list[OCRBlock] = []
    text_parts: list[str] = []
    for region in regions:
        content = (region.get("block_content") or "").strip()
        if not content:
            continue
        bbox = _as_bbox(region.get("block_bbox"))
        block_type = region.get("block_label") or region.get("type")
        blocks.append(
            OCRBlock(
                text=content,
                confidence=None,
                bbox=bbox,
                block_type=str(block_type) if block_type else None,
            )
        )
        text_parts.append(content)

    scores = _extract_overall_scores(payload_obj)
    confidence = sum(scores) / len(scores) if scores else None
    markdown = _extract_markdown(payload_obj)
    return blocks, confidence, markdown


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@dataclass
class _PipelineHolder:
    """Lazily-built singleton holding the PaddleX pipeline."""

    profile: StructureProfile
    device: str
    engine_factory: Callable[[], Any] | None
    _instance: Any = None

    def get(self) -> Any:
        if self._instance is not None:
            return self._instance
        if self.engine_factory is not None:
            self._instance = self.engine_factory()
            return self._instance
        self._instance = self._default_init()
        return self._instance

    def _default_init(self) -> Any:
        """Try PPStructureV3, fall back to ``paddlex.create_pipeline``."""
        if self.profile.prefer_v3:
            try:
                from paddlex import PPStructureV3  # type: ignore[attr-defined]

                instance = PPStructureV3(device=self.device)
                logger.info(
                    "structure_adapter: PPStructureV3 ready (profile=%s, device=%s)",
                    self.profile.id,
                    self.device,
                )
                return instance
            except Exception as exc:
                logger.warning(
                    "structure_adapter: PPStructureV3 unavailable (%s); falling back to "
                    "paddlex.create_pipeline(%r)",
                    exc,
                    self.profile.pipeline,
                )

        from paddlex import create_pipeline

        return create_pipeline(pipeline=self.profile.pipeline, device=self.device)


class StructureAdapter:
    """Single entry point for running PP-Structure / layout_parsing."""

    def __init__(
        self,
        *,
        profile: StructureProfile | None = None,
        device: str = "gpu",
        engine_factory: Callable[[], Any] | None = None,
        export_markdown: bool = True,
        export_json: bool = True,
        settings: object | None = None,
        log_runtime_info: bool = True,
    ) -> None:
        if device != "gpu":
            raise RuntimeError(
                "PP-Structure / layout_parsing is GPU-only: PaddlePaddle 3.x's "
                "PIR executor crashes layout_parsing on CPU with "
                "'NotImplementedError: ConvertPirAttribute2RuntimeAttribute'. "
                "Use PaddleOCR (Tier 2) on CPU workers."
            )
        self._profile_override = profile
        self.device = device
        self._engine_factory = engine_factory
        self.export_markdown = export_markdown
        self.export_json = export_json
        self.log_runtime_info = log_runtime_info
        self.profile: StructureProfile = (
            profile if profile is not None else resolve_structure_pipeline(settings)
            if settings is not None
            else _default_structure_profile()
        )
        self._holder = _PipelineHolder(
            profile=self.profile,
            device=device,
            engine_factory=engine_factory,
        )

    @property
    def name(self) -> str:
        return "pp_structure"

    def run(self, image_path: Path) -> OCRResult:
        try:
            pipeline = self._holder.get()
        except Exception:
            raise
        if self.log_runtime_info and not getattr(self, "_logged_runtime", False):
            self._log_runtime_info()
            self._logged_runtime = True

        results_iter = self._invoke_pipeline(pipeline, str(image_path))
        results = list(results_iter) if results_iter is not None else []
        blocks: list[OCRBlock] = []
        text_parts: list[str] = []
        confidences: list[float] = []
        markdown_chunks: list[str] = []

        for result in results:
            r_blocks, r_conf, r_md = normalize_structure_output(result)
            blocks.extend(r_blocks)
            text_parts.extend(b.text for b in r_blocks if b.text)
            if r_conf is not None:
                confidences.append(r_conf)
            if self.export_markdown and r_md:
                markdown_chunks.append(r_md)

        confidence = sum(confidences) / len(confidences) if confidences else None
        text = "\n".join(text_parts)
        if self.export_markdown and markdown_chunks:
            text = text + "\n\n" + "\n\n".join(markdown_chunks) if text else "\n\n".join(markdown_chunks)
        return OCRResult(text=text, confidence=confidence, blocks=blocks, engine=self.name)

    def _invoke_pipeline(self, pipeline: Any, path: str) -> Iterable[Any] | None:
        """Call ``predict`` if available, else raise a clear error."""
        if callable(getattr(pipeline, "predict", None)):
            try:
                return list(pipeline.predict(path))
            except TypeError:
                # Some PaddleX versions return a generator that must be consumed.
                return pipeline.predict(path)
        raise RuntimeError(
            "structure_adapter: pipeline object has no predict() method; "
            f"got {type(pipeline).__name__}"
        )

    def _log_runtime_info(self) -> None:
        if not self.log_runtime_info:
            return
        try:
            import paddlex as _paddlex_mod  # noqa: F401

            paddlex_version = getattr(_paddlex_mod, "__version__", "unknown")
        except Exception:
            paddlex_version = "unavailable"
        logger.info(
            "structure_adapter ready profile=%s pipeline=%s device=%s paddlex_version=%s",
            self.profile.id,
            self.profile.pipeline,
            self.device,
            paddlex_version,
        )


def _default_structure_profile() -> StructureProfile:
    from app.ocr.model_registry import get_structure_profile

    return get_structure_profile(None)


__all__ = [
    "StructureAdapter",
    "normalize_structure_output",
]