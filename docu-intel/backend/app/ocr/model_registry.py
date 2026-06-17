"""OCR model registry (future-proof profile resolver).

This module centralises **what model profiles the OCR adapters know
about**. It is the single place to add, deprecate or rename profiles so
that ``paddle_adapter`` and ``structure_adapter`` never hardcode model
names and so that operators can flip between PP-OCRv3 / PP-OCRv4 /
PP-OCRv5 / PP-OCRv6 / PP-StructureV2 / PP-StructureV3 by changing
settings alone.

Design contract:

* **No PaddleOCR / PaddleX import.** This module is pure configuration.
  Importing it must not download models, must not touch the GPU and
  must not require paddleocr / paddlex to be installed.
* **No global state at import time.** All registries are built lazily
  by the public helpers (``get_ocr_profile`` etc.) from immutable dicts
  declared at module level.
* **Profiles are data, not behaviour.** The adapter modules translate a
  ``OcrProfile`` into a PaddleOCR/PaddleX constructor call; the registry
  itself never opens a model.

Profile layout::

    OcrProfile(
        id="ppocr_v6_medium",
        backend="paddleocr",
        model_type="PP-OCRv6",
        detection_model_name="...",   # PaddleOCR arg
        recognition_model_name="...", # PaddleOCR arg (optional override)
        use_predict_api=True,         # prefer predict() over ocr() when available
        description="...",
    )

Operators set ``PADDLE_OCR_PROFILE=ppocr_v6_medium`` (or any other
known id) in the environment and the adapter picks the right profile
on first use. Unknown ids fall back to the default profile and log a
warning so the misconfiguration is visible without breaking ingestion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Mapping


logger = logging.getLogger("app.ocr.model_registry")


# ---------------------------------------------------------------------------
# OCR (PaddleOCR) profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OcrProfile:
    """A named bundle of PaddleOCR model choices.

    ``backend`` is currently always ``"paddleocr"`` but the field exists
    so a future cloud-OCR adapter can register its own profiles under
    the same registry API.
    """

    id: str
    backend: str
    model_type: str
    detection_model_name: str | None
    recognition_model_name: str | None
    use_predict_api: bool
    description: str = ""
    extra: Mapping[str, object] = field(default_factory=dict)


# Stable set of profiles shipped with the project.  The ids are the
# canonical identifiers operators set in ``PADDLE_OCR_PROFILE``.
_OCR_PROFILES: dict[str, OcrProfile] = {
    "ppocr_v5_server": OcrProfile(
        id="ppocr_v5_server",
        backend="paddleocr",
        model_type="PP-OCRv5",
        detection_model_name=None,
        recognition_model_name=None,
        use_predict_api=True,
        description="PP-OCRv5 server profile (largest, best accuracy, slowest).",
    ),
    "ppocr_v6_tiny": OcrProfile(
        id="ppocr_v6_tiny",
        backend="paddleocr",
        model_type="PP-OCRv6",
        detection_model_name=None,
        recognition_model_name=None,
        use_predict_api=True,
        description="PP-OCRv6 tiny profile (fastest, CPU-friendly baseline).",
    ),
    "ppocr_v6_small": OcrProfile(
        id="ppocr_v6_small",
        backend="paddleocr",
        model_type="PP-OCRv6",
        detection_model_name=None,
        recognition_model_name=None,
        use_predict_api=True,
        description="PP-OCRv6 small profile (balanced accuracy / speed).",
    ),
    "ppocr_v6_medium": OcrProfile(
        id="ppocr_v6_medium",
        backend="paddleocr",
        model_type="PP-OCRv6",
        detection_model_name=None,
        recognition_model_name=None,
        use_predict_api=True,
        description="PP-OCRv6 medium profile (default — accuracy / speed sweet spot).",
    ),
    "custom": OcrProfile(
        id="custom",
        backend="paddleocr",
        model_type="PP-OCR",
        detection_model_name=None,
        recognition_model_name=None,
        use_predict_api=True,
        description="Custom profile — relies on PADDLE_TEXT_DETECTION_MODEL_NAME / "
        "PADDLE_TEXT_RECOGNITION_MODEL_NAME overrides from settings.",
    ),
}


_DEFAULT_OCR_PROFILE_ID = "ppocr_v6_medium"


# ---------------------------------------------------------------------------
# Structure (PaddleX / PP-Structure) profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StructureProfile:
    """A named bundle of PaddleX PP-Structure / layout_parsing choices."""

    id: str
    backend: str
    pipeline: str
    prefer_v3: bool
    description: str = ""
    extra: Mapping[str, object] = field(default_factory=dict)


_STRUCTURE_PROFILES: dict[str, StructureProfile] = {
    "pp_structure_v3": StructureProfile(
        id="pp_structure_v3",
        backend="paddlex",
        pipeline="layout_parsing",
        prefer_v3=True,
        description="PP-StructureV3 via PPStructureV3 when available, else "
        "paddlex.create_pipeline('layout_parsing').",
    ),
    "layout_parsing_legacy": StructureProfile(
        id="layout_parsing_legacy",
        backend="paddlex",
        pipeline="layout_parsing",
        prefer_v3=False,
        description="Legacy paddlex.create_pipeline('layout_parsing') path "
        "only — useful as a rollback when PPStructureV3 is unstable.",
    ),
    "custom": StructureProfile(
        id="custom",
        backend="paddlex",
        pipeline="layout_parsing",
        prefer_v3=True,
        description="Custom profile — relies on PP_STRUCTURE_PIPELINE_NAME "
        "override from settings.",
    ),
}


_DEFAULT_STRUCTURE_PROFILE_ID = "pp_structure_v3"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_ocr_profiles() -> list[OcrProfile]:
    """Return every OCR profile shipped with the project."""
    return list(_OCR_PROFILES.values())


def list_structure_profiles() -> list[StructureProfile]:
    """Return every structure profile shipped with the project."""
    return list(_STRUCTURE_PROFILES.values())


def get_ocr_profile(profile_id: str | None) -> OcrProfile:
    """Resolve an OCR profile id to its :class:`OcrProfile`.

    ``None`` / empty string / unknown id → default profile, with a
    warning logged for the unknown case so operators notice a typo
    instead of silently using the fallback.
    """
    if not profile_id:
        return _OCR_PROFILES[_DEFAULT_OCR_PROFILE_ID]
    profile = _OCR_PROFILES.get(profile_id)
    if profile is None:
        logger.warning(
            "Unknown paddle_ocr_profile=%r, falling back to %s",
            profile_id,
            _DEFAULT_OCR_PROFILE_ID,
        )
        return _OCR_PROFILES[_DEFAULT_OCR_PROFILE_ID]
    return profile


def get_structure_profile(profile_id: str | None) -> StructureProfile:
    """Resolve a structure profile id to its :class:`StructureProfile`."""
    if not profile_id:
        return _STRUCTURE_PROFILES[_DEFAULT_STRUCTURE_PROFILE_ID]
    profile = _STRUCTURE_PROFILES.get(profile_id)
    if profile is None:
        logger.warning(
            "Unknown pp_structure_profile=%r, falling back to %s",
            profile_id,
            _DEFAULT_STRUCTURE_PROFILE_ID,
        )
        return _STRUCTURE_PROFILES[_DEFAULT_STRUCTURE_PROFILE_ID]
    return profile


def resolve_ocr_models(settings: object) -> OcrProfile:
    """Resolve the OCR profile using the project's ``Settings`` object.

    The function reads (in order of precedence):

    * ``settings.paddle_ocr_profile`` — the named profile id
    * ``settings.paddle_text_detection_model_name`` — detection override
    * ``settings.paddle_text_recognition_model_name`` — recognition override

    If a custom detection/recognition model name is set the resolved
    profile is cloned (``dataclasses.replace``) with the overrides so
    the registry dict stays immutable.
    """
    profile_id = getattr(settings, "paddle_ocr_profile", None) or _DEFAULT_OCR_PROFILE_ID
    profile = get_ocr_profile(profile_id)

    detection = getattr(settings, "paddle_text_detection_model_name", None)
    recognition = getattr(settings, "paddle_text_recognition_model_name", None)
    use_predict = getattr(settings, "paddle_use_predict_api", profile.use_predict_api)
    force_legacy = getattr(settings, "paddle_force_legacy_ocr_api", False)
    force_predict = getattr(settings, "paddle_force_predict_api", False)

    # If the operator forces the legacy API, prefer it regardless of profile.
    if force_legacy:
        use_predict = False
    if force_predict:
        use_predict = True

    overrides: dict[str, object] = {}
    if detection:
        overrides["detection_model_name"] = detection
    if recognition:
        overrides["recognition_model_name"] = recognition
    overrides["use_predict_api"] = use_predict

    if overrides:
        return replace(profile, **overrides)
    return profile


def resolve_structure_pipeline(settings: object) -> StructureProfile:
    """Resolve the structure profile using the project's ``Settings`` object.

    Reads ``settings.pp_structure_profile`` and
    ``settings.pp_structure_pipeline_name``. The latter only applies to
    the ``custom`` profile so the canonical ``pp_structure_v3`` id keeps
    its standard pipeline name.
    """
    profile_id = getattr(settings, "pp_structure_profile", None) or _DEFAULT_STRUCTURE_PROFILE_ID
    profile = get_structure_profile(profile_id)

    pipeline_name = getattr(settings, "pp_structure_pipeline_name", None)
    prefer_v3 = getattr(settings, "pp_structure_use_v3", profile.prefer_v3)
    force_fallback = getattr(settings, "pp_structure_force_paddlex_fallback", False)

    if force_fallback:
        # Operator explicitly disabled V3 — switch to the legacy profile.
        return get_structure_profile("layout_parsing_legacy")

    overrides: dict[str, object] = {"prefer_v3": prefer_v3}
    if profile.id == "custom" and pipeline_name:
        overrides["pipeline"] = pipeline_name
    return replace(profile, **overrides)


__all__ = [
    "OcrProfile",
    "StructureProfile",
    "list_ocr_profiles",
    "list_structure_profiles",
    "get_ocr_profile",
    "get_structure_profile",
    "resolve_ocr_models",
    "resolve_structure_pipeline",
]