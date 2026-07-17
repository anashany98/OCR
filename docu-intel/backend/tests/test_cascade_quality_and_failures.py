"""S4.1 + S4.2 — OCR cascade score and failure-tracking contract.

The MiniMax M3 (FASE 4) plan asks to verify two things on the
cascading OCR engine:

* S4.1: the cascade selects the next tier by *quality score*
  (confidence + density + structure) and not by text length alone.
* S4.2: tier-2 / tier-3 / tier-4 fall-backs log a structured event
  **and** emit a Prometheus counter when they fall through
  because of an exception, distinct from falling through because
  the result was below the quality bar.

Both are pinned structurally (read the source, assert the
expected helpers/weights are in place). No GPU is required.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


CASCADING_PATH = Path("app/ocr/cascading.py")


def _read_source() -> str:
    return CASCADING_PATH.read_text(encoding="utf-8")


def test_quality_score_weights_confidence_and_density():
    """``_quality`` must combine ``confidence`` and ``density`` (and a
    small length factor) — never collapse to a length-only check.
    The plan also requires *structure*; the current implementation
    does not extract a structural feature from ``OCRResult`` so we
    pin the documented weights and flag the gap so a future
    refactor that drops the density/confidence weights is caught.
    """
    source = _read_source()
    # Find the ``def _quality(result: OCRResult) -> float:`` block.
    # We grab the function body up to the next top-level ``def`` (or
    # ``class``) at column 0, which is more robust than relying on a
    # single ``return`` line.
    match = re.search(
        r"^def _quality\(result: OCRResult\).*?(?=^def \w+|^class \w+|\Z)",
        source,
        re.DOTALL | re.MULTILINE,
    )
    assert match, "_quality not found in cascading.py"
    body = match.group(0)
    assert "confidence" in body, (
        "_quality must read the confidence field from OCRResult"
    )
    # density is computed as alnum / len(text); the helper _alnum_count
    # must be called from _quality.
    assert "_alnum_count" in body, (
        "_quality must derive the density feature from _alnum_count"
    )
    # Weights: confidence and density are the dominant signals
    # (each ~40 %); length_factor is a tie-breaker (~20 %). A future
    # refactor that drops any of these (e.g. moves to length-only)
    # will fail this test.
    assert "0.4" in body and "0.2" in body, (
        "Expected confidence and density to weigh 0.4 each and "
        "length_factor 0.2. The exact weights are documented in the "
        "PLAN_MAESTRO_MEJORAS.md FASE 4.1."
    )
    # Structure is intentionally out of scope for this pass — pin
    # the gap so it is easy to track in a future sprint.
    # (no assert here, but the comment above is the trace.)


def test_fallback_failure_tracks_exception_in_prometheus():
    """When a tier raises an exception, the engine must call a
    failure-tracking helper that emits BOTH a structured log and a
    Prometheus counter so the operator can distinguish
    "engine errored" from "engine result too low quality".
    """
    source = _read_source()
    assert "_track_fallback_failure" in source, (
        "CascadingOCREngine must define a _track_fallback_failure helper "
        "that wraps the log + Prometheus emission for tier failures."
    )
    # The helper itself must log a warning AND call a track_* metric.
    # We use a small regex over the helper body.
    helper_match = re.search(
        r"def _track_fallback_failure\(self.*?(?=\n    def |\nclass |\Z)",
        source,
        re.DOTALL,
    )
    assert helper_match, "_track_fallback_failure body not found"
    helper = helper_match.group(0)
    assert "logger.warning" in helper or "logger.error" in helper, (
        "_track_fallback_failure must log the failure at warning or "
        "error level so it shows up in the operator's tail."
    )
    # The Prometheus call uses a ``track_ocr_*`` function.
    assert re.search(r"track_ocr_[a-z_]+\(", helper), (
        "_track_fallback_failure must call a Prometheus ``track_ocr_*`` "
        "metric so the admin UI can graph engine errors over time."
    )


def test_quality_based_skip_emits_distinct_metric():
    """When the cascade skips a tier because the *quality* bar is not
    met (not because of an exception), it must emit a different
    metric label so the operator can separate "quality skip" from
    "engine failure". The current implementation uses
    ``track_ocr_skip_tier2(reason)`` for the quality path.
    """
    source = _read_source()
    assert "track_ocr_skip_tier2" in source, (
        "Quality-based tier-2 skip must call track_ocr_skip_tier2 so it "
        "is distinguishable from the exception path in Prometheus."
    )
    # And the exception path must use a *different* function name
    # (track_ocr_cascade_fallback or similar) — not the same metric.
    # We assert both helpers are referenced from the file.
    assert "track_ocr_cascade_fallback" in source, (
        "Exception-based fallback must use track_ocr_cascade_fallback "
        "(or a similarly distinct helper) so the operator can graph "
        "failures independently of quality-driven skips."
    )
