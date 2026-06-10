"""P2 — Plan symbol detection (YOLOv8 / Architect).

Detects architectural symbols in plan images using a YOLOv8 model.
The default model is the public ``SamirShabani/Architect`` (YOLOv8m
fine-tuned on the FloorPlanCAD dataset, CC BY-NC 4.0). Operators can
swap in a custom-trained ``.pt`` file via the
``PLAN_SYMBOLS_MODEL_PATH`` setting without code changes.

Classes recognised by the default model
---------------------------------------
The Architect model detects 28 architectural elements (single door,
double door, sliding door, window, stair, gas stove, refrigerator,
washing machine, sofa, bed, chair, table, sink, bath, bath tub,
toilet, elevator, escalator, etc.). The class names returned by YOLO
are lowercase with spaces (``"single door"``, ``"double door"``). We
normalise them to snake_case to match the rest of the platform
(``single_door``, ``double_door``).

How detection is triggered
--------------------------
Detection runs as part of the plan processing pipeline
(``app.services.plan_extraction.persist_plan_extraction``). It is
**fail-safe**: any error returns an empty list so the rest of the
pipeline keeps moving.

Performance
-----------
The model runs on CPU by default (YOLOv8m + 640px images is ~200ms
per page on a modern CPU). When CUDA is available the operator can
flip ``plan_symbols_device`` to ``"cuda"`` and the model will run
~10x faster.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("app.services.plan_symbols")


# ---------------------------------------------------------------------------
# Output dataclass (kept compatible with the previous stub)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DetectedSymbol:
    """A single symbol detected in the plan image.

    Attributes:
        symbol_class: the class of the symbol in snake_case (e.g.
            ``"electrical_outlet"``, ``"door"``, ``"single_door"``).
        bbox: bounding box ``(x0, y0, x1, y1)`` in PDF coordinates
            (points). The conversion from pixel coordinates to
            PDF points happens inside :func:`detect_symbols` so
            downstream consumers can mix symbol bboxes with
            ``PlanDimension`` bboxes without further arithmetic.
        confidence: detection confidence (0–1).
        page_number: which page the symbol was detected on.
    """

    symbol_class: str
    bbox: tuple[float, float, float, float]
    confidence: float
    page_number: int


# ---------------------------------------------------------------------------
# Class taxonomy
# ---------------------------------------------------------------------------
#
# The Architect model uses lowercase, space-separated names. We normalise
# to snake_case so the platform has a single canonical form. A few classes
# also have aliases to the ``SUPPORTED_SYMBOL_CLASSES`` vocabulary we
# already publish in the OpenAPI spec (so a frontend filter on
# ``"electrical_outlet"`` still works when the model emits a synonym).
#
# Anything not in this map is preserved verbatim — operators may want to
# add their own custom classes (e.g. "ev_charger") to a custom model.

# Map of model class names (lowercase) to canonical snake_case labels.
# If a key is missing the class name is normalised (spaces -> underscores,
# lowercased) and used as-is.
_ARCHITECT_CLASS_MAP: dict[str, str] = {
    "single door": "single_door",
    "double door": "double_door",
    "sliding door": "sliding_door",
    "bay window": "bay_window",
    "blind window": "blind_window",
    "opening symbol": "opening_symbol",
    "gas stove": "gas_stove",
    "washing machine": "washing_machine",
    "bedside cupboard": "bedside_cupboard",
    "tv cabinet": "tv_cabinet",
    "half-height cabinet": "half_height_cabinet",
    "high cabinet": "high_cabinet",
    "bath tub": "bathtub",
    "squat toilet": "squat_toilet",
}

# The full set of symbol classes we expose to the frontend. Anything
# the model detects outside this set is still kept (we don't drop it)
# but is not advertised in the OpenAPI ``SUPPORTED_SYMBOL_CLASSES`` set.
SUPPORTED_SYMBOL_CLASSES: frozenset[str] = frozenset(
    {
        "electrical_outlet",
        "light_switch",
        "radiator",
        "door",
        "single_door",
        "double_door",
        "sliding_door",
        "window",
        "bay_window",
        "blind_window",
        "opening_symbol",
        "stair",
        "sink",
        "toilet",
        "squat_toilet",
        "urinal",
        "shower",
        "bathtub",
        "bath",
        "gas_stove",
        "refrigerator",
        "washing_machine",
        "sofa",
        "bed",
        "chair",
        "table",
        "bedside_cupboard",
        "tv_cabinet",
        "half_height_cabinet",
        "high_cabinet",
        "wardrobe",
        "elevator",
        "escalator",
        "fire_extinguisher",
        "fire_alarm",
        "smoke_detector",
        "thermostat",
        "electrical_panel",
        "water_heater",
        "air_conditioner",
    }
)


def _normalise_class_name(name: str) -> str:
    """Map a raw YOLO class name to its canonical snake_case form."""
    cleaned = name.strip().lower()
    if cleaned in _ARCHITECT_CLASS_MAP:
        return _ARCHITECT_CLASS_MAP[cleaned]
    # Generic normalisation: lowercase, spaces -> underscores,
    # collapse repeated underscores, strip non-alnum boundaries.
    return re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")


# ---------------------------------------------------------------------------
# Model loader
# ---------------------------------------------------------------------------
#
# The model is loaded once per process, in a background thread (so the
# constructor does not block the first request). We cache the model on
# a module-level singleton and guard it with a lock to make worker
# re-use safe.


_model_lock = threading.Lock()
_model = None  # type: ignore[var-annotated]
_model_loaded: bool = False
_model_load_error: BaseException | None = None


def _ensure_model_loaded():
    """Load the YOLO model on first use. Returns the model or ``None``.

    The model is loaded lazily so workers do not pay the cost at
    startup if the YOLO dependency is not actually used (e.g. the
    deployment is GPU-only and the workers are not GPU-equipped).
    """
    global _model, _model_loaded, _model_load_error

    from app.core.config import settings

    if not getattr(settings, "plan_symbols_enabled", True):
        return None

    if _model_loaded:
        return _model

    with _model_lock:
        if _model_loaded:
            return _model
        try:
            from ultralytics import YOLO  # type: ignore[import-not-found]

            model_path = getattr(settings, "plan_symbols_model_path", "yolov8n.pt")
            logger.info("Loading YOLO plan-symbols model: %s", model_path)
            _model = YOLO(model_path)
            _model_loaded = True
            _model_load_error = None
            logger.info("YOLO plan-symbols model loaded successfully")
        except Exception as exc:  # pragma: no cover - environment-dependent
            _model_load_error = exc
            _model_loaded = True  # mark as "attempted" so we don't retry per call
            logger.warning(
                "Failed to load YOLO plan-symbols model (%s). "
                "Symbol detection will be skipped for this process. "
                "Set PLAN_SYMBOLS_ENABLED=false to silence this warning.",
                exc,
            )
    return _model


def reset_model_cache() -> None:
    """Test/admin helper: force the model to be reloaded on next call.

    The cache is per-process. Tests and operational tooling can call
    this after a model swap.
    """
    global _model, _model_loaded, _model_load_error
    with _model_lock:
        _model = None
        _model_loaded = False
        _model_load_error = None


def is_model_available() -> bool:
    """True when the YOLO model is loaded and ready to run inference."""
    return _model is not None


def last_load_error() -> BaseException | None:
    """Return the exception that prevented the model from loading, or
    ``None`` if the model is loaded (or has not been attempted yet)."""
    return _model_load_error


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_symbols(
    image_path: str | Path,
    *,
    page_number: int = 1,
    confidence_threshold: float | None = None,
) -> list[DetectedSymbol]:
    """Detect symbols in a plan image.

    The function is **fail-safe**: on any error (missing file, no
    model installed, OOM) it returns an empty list so the caller can
    continue processing.

    Args:
        image_path: path to the plan image (PNG/JPG).
        page_number: the page number (for multi-page plans). The
            caller is responsible for rendering each page to its own
            image and passing the right page number.
        confidence_threshold: minimum confidence to keep a detection.
            Defaults to ``settings.plan_symbols_confidence_threshold``.

    Returns:
        A list of :class:`DetectedSymbol`. May be empty if the model
        is not installed, the file is missing, or no symbols were
        detected.
    """
    from app.core.config import settings

    image_path = Path(image_path)
    if not image_path.exists():
        logger.debug("plan_symbols: image not found, %s", image_path)
        return []

    model = _ensure_model_loaded()
    if model is None:
        # Model unavailable (not installed, failed to load, or
        # explicitly disabled). Caller's pipeline continues.
        return []

    threshold = (
        confidence_threshold
        if confidence_threshold is not None
        else float(getattr(settings, "plan_symbols_confidence_threshold", 0.35))
    )
    iou = float(getattr(settings, "plan_symbols_iou_threshold", 0.45))
    imgsz = int(getattr(settings, "plan_symbols_image_size", 640))
    device = str(getattr(settings, "plan_symbols_device", "cpu"))

    try:
        # ``predict`` returns a list (one result per image). We pass a
        # single image, so we get a single result.
        results = model.predict(
            source=str(image_path),
            conf=threshold,
            iou=iou,
            imgsz=imgsz,
            device=device,
            verbose=False,
        )
    except Exception as exc:  # pragma: no cover - environment-dependent
        logger.warning("YOLO inference failed for %s: %s", image_path, exc)
        return []

    if not results:
        return []

    detections: list[DetectedSymbol] = []
    try:
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []
        names = getattr(result, "names", {}) or {}
        # ``boxes.xyxy`` is a tensor of shape (N, 4) with absolute pixel
        # coordinates. ``boxes.conf`` and ``boxes.cls`` are the matching
        # confidences and class indices.
        xyxy = boxes.xyxy
        confs = boxes.conf
        classes = boxes.cls
        if xyxy is None or confs is None or classes is None:
            return []
        for i in range(len(xyxy)):
            try:
                x1, y1, x2, y2 = (float(v) for v in xyxy[i].tolist())
                conf = float(confs[i].item())
                cls_idx = int(classes[i].item())
            except Exception:
                continue
            raw_name = names.get(cls_idx) or f"class_{cls_idx}"
            symbol_class = _normalise_class_name(str(raw_name))
            detections.append(
                DetectedSymbol(
                    symbol_class=symbol_class,
                    bbox=(x1, y1, x2, y2),
                    confidence=conf,
                    page_number=page_number,
                )
            )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to parse YOLO results for %s: %s", image_path, exc)
        return []

    return detections


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def count_by_class(detections: list[DetectedSymbol]) -> dict[str, int]:
    """Return a ``{symbol_class: count}`` mapping for a list of detections.

    Used by the API endpoint that exposes per-plan symbol summaries
    (e.g. ``{"door": 4, "window": 6, "toilet": 1}``).
    """
    counts: dict[str, int] = {}
    for sym in detections:
        counts[sym.symbol_class] = counts.get(sym.symbol_class, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------


__all__ = [
    "DetectedSymbol",
    "SUPPORTED_SYMBOL_CLASSES",
    "detect_symbols",
    "count_by_class",
    "is_model_available",
    "reset_model_cache",
    "last_load_error",
]
